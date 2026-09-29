"""Local research dashboard. Workers use exactly the same CLI run service."""

import argparse
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from tass.config import ScenarioConfig, load_config
from tass.llm import resolve_model
from tass.runner import estimated_cost, request_pause
from tass.scenarios import load_scenario
from tass.storage import RunStore


def launch_worker(directory: Path, config: Path | None = None, mode="baseline"):
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "tass.cli", "run"]
    command += (
        ["--config", str(config), "--output", str(directory), "--mode", mode]
        if config
        else ["--resume", str(directory)]
    )
    with (directory / "worker.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    return process.pid


def town_figure(world):
    figure = go.Figure()
    for start, end in world.locations.edges:
        start_pos = world.locations.nodes[start]["pos"]
        end_pos = world.locations.nodes[end]["pos"]
        figure.add_trace(
            go.Scatter(
                x=[start_pos[0], end_pos[0]],
                y=[start_pos[1], end_pos[1]],
                mode="lines",
                line={"color": "#cad5df", "width": 3},
                hoverinfo="skip",
                showlegend=False,
            )
        )
    figure.add_trace(
        go.Scatter(
            x=[world.locations.nodes[name]["pos"][0] for name in world.locations],
            y=[world.locations.nodes[name]["pos"][1] for name in world.locations],
            text=list(world.locations),
            mode="markers+text",
            textposition="top center",
            marker={"size": 45, "color": "#e7edf4", "symbol": "square"},
            name="场所",
        )
    )
    colors = {"resident": "#2b7a78", "shop": "#d18536", "producer": "#6554a4"}
    for role, color in colors.items():
        actors = [
            actor.state for actor in world.actors.values() if actor.state.profile.role == role
        ]
        horizontal, vertical = [], []
        for index, actor in enumerate(actors):
            origin = world.locations.nodes[actor.location]["pos"]
            angle = index * 2.399
            radius = 0.09 + 0.035 * (index % 4)
            horizontal.append(origin[0] + radius * math.cos(angle))
            vertical.append(origin[1] + radius * math.sin(angle))
        figure.add_trace(
            go.Scatter(
                x=horizontal,
                y=vertical,
                mode="markers",
                text=[
                    f"{actor.profile.name} · {actor.profile.agent_id}<br>{actor.location}"
                    for actor in actors
                ],
                hovertemplate="%{text}<extra></extra>",
                marker={"size": 12, "color": color},
                name=role,
            )
        )
    figure.update_layout(
        height=460,
        margin={"l": 20, "r": 20, "t": 25, "b": 15},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#f6f8fb",
        xaxis={"visible": False},
        yaxis={"visible": False},
        legend={"orientation": "h"},
    )
    return figure


def social_figure(world):
    positions = nx.spring_layout(world.social, seed=42)
    horizontal, vertical = [], []
    for start, end in world.social.edges:
        horizontal += [positions[start][0], positions[end][0], None]
        vertical += [positions[start][1], positions[end][1], None]
    figure = go.Figure(
        go.Scatter(
            x=horizontal,
            y=vertical,
            mode="lines",
            line={"color": "#cdd7e2", "width": 1},
            hoverinfo="skip",
        )
    )
    identifiers = list(world.social)
    figure.add_trace(
        go.Scatter(
            x=[positions[actor][0] for actor in identifiers],
            y=[positions[actor][1] for actor in identifiers],
            text=identifiers,
            mode="markers",
            hovertemplate="%{text}<extra></extra>",
            marker={"size": 13, "color": "#2b7a78"},
        )
    )
    figure.update_layout(
        height=440,
        showlegend=False,
        xaxis={"visible": False},
        yaxis={"visible": False},
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
    )
    return figure


@st.fragment(run_every="2s")
def render_run(directory: Path):
    if not (directory / "run.sqlite").exists():
        st.info("运行正在初始化，页面会自动刷新。")
        return
    store = RunStore(directory)
    try:
        raw_config = store.get("config")
        if not raw_config:
            st.info("正在加载配置。")
            return
        config = ScenarioConfig.model_validate(raw_config)
        status = store.get("status", "initializing")
        latest = store.snapshot()
        if latest is None:
            st.info("等待第一个检查点。")
            return
        usage = store.usage()
        validation = store.get("validation")
        st.caption(f"{directory.name}  /  {config.scenario}  /  {validation}")
        if config.mode == "baseline":
            st.info("离线规则基线 · 未调用真实 LLM；这些结果用于验证环境与工程功能。")
        else:
            st.info(f"LLM 模式 · 验证来源：{validation} · 当前状态：{status}")
        controls = st.columns([2, 1, 1])
        controls[0].write(f"运行状态：**{status}**")
        if controls[1].button("暂停", disabled=status != "running", key=f"pause-{directory}"):
            request_pause(directory)
            st.toast("已请求在当前时段完成后暂停")
        if controls[2].button(
            "恢复",
            disabled=status not in ("paused", "failed", "interrupted"),
            key=f"resume-{directory}",
        ):
            launch_worker(directory)
            st.toast("恢复任务已启动")
        columns = st.columns(4)
        columns[0].metric("已完成时段", f"{latest['tick']} / {config.total_ticks}")
        columns[1].metric("社会主体", len(latest["actors"]))
        columns[2].metric("API 请求", usage["requests"])
        columns[3].metric(
            "输入 / 输出 tokens", f"{usage['input_tokens']:,} / {usage['output_tokens']:,}"
        )
        cost = estimated_cost(usage, config)
        st.caption(
            "调用费用：未配置单价；请参照 token 用量及服务商账单。"
            if cost is None
            else f"累计估算费用：{cost:.6f}（使用配置中的每百万 token 单价）"
        )
        follow = st.toggle("跟随最新状态", value=True, key=f"follow-{directory}")
        selected_tick = latest["tick"] - 1
        if not follow:
            selected_tick = st.select_slider(
                "回放时段（-1 为初始状态）",
                options=list(range(-1, latest["tick"])),
                value=selected_tick,
                key=f"tick-{directory}",
            )
        snapshot = store.snapshot(selected_tick)
        world = load_scenario(config.scenario).restore_world(config, snapshot)
        metrics = pd.DataFrame(
            [metric for metric in store.metrics() if metric["tick"] <= selected_tick]
        )
        tabs = st.tabs(["小镇", "角色与记忆", "关系网络", "经济与合同", "事件审计"])
        with tabs[0]:
            st.plotly_chart(town_figure(world), width="stretch", key=f"town-{directory}")
            st.caption("角色位置属于离散场所网络；同一时段的决策基于同一份世界状态。")
            if not metrics.empty:
                available = [
                    name
                    for name in ("employed", "consumption", "unmet_needs", "contributions")
                    if name in metrics
                ]
                st.line_chart(metrics.set_index("tick")[available])
        with tabs[1]:
            actor_id = st.selectbox("选择角色", list(world.actors), key=f"actor-{directory}")
            state = world.state(actor_id)
            left, right = st.columns(2)
            left.json(state.model_dump(exclude={"memories"}))
            right.write("可追溯记忆（研究者审计视图）")
            right.json(state.memories[-config.memory_limit :])
            with st.expander("本时段决策前的实际观察与提交行动"):
                observation = store.observation(selected_tick, actor_id)
                decision = store.decision(selected_tick, actor_id)
                if observation is None:
                    st.info("初始检查点或旧运行未保存这一时段的观察。")
                else:
                    st.json(observation.model_dump())
                if decision is not None:
                    st.json(decision.model_dump())
        with tabs[2]:
            st.plotly_chart(social_figure(world), width="stretch", key=f"social-{directory}")
            st.caption("连线表示通信关系；参加同一社区活动可以建立新关系。")
        with tabs[3]:
            residents = [
                actor.state
                for actor in world.actors.values()
                if actor.state.profile.role == "resident"
            ]
            if residents:
                wealth = go.Figure(
                    go.Bar(
                        x=[resident.profile.agent_id for resident in residents],
                        y=[resident.cash for resident in residents],
                        marker_color="#2b7a78",
                    )
                )
                wealth.update_layout(
                    title="居民现金分布（不含库存与托管资产）",
                    yaxis_title="最小货币单位",
                    height=320,
                )
                st.plotly_chart(wealth, width="stretch", key=f"wealth-{directory}")
            if not metrics.empty:
                available = [
                    name
                    for name in ("resident_cash", "treasury", "trade_volume", "policy_spending")
                    if name in metrics
                ]
                st.line_chart(metrics.set_index("tick")[available])
                st.dataframe(metrics, hide_index=True, width="stretch")
            st.write("合同")
            st.dataframe(
                pd.DataFrame([contract.model_dump() for contract in world.contracts.values()]),
                hide_index=True,
                width="stretch",
            )
        with tabs[4]:
            events = store.events(selected_tick)
            st.caption("研究者可审阅全部事件；角色只接收 visible_to 授权的观察。")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            key: event[key]
                            for key in ("event_id", "tick", "kind", "actor", "source_type")
                        }
                        for event in events
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            st.json(events[-30:])
            for filename in ("metrics.csv", "events.jsonl", "run.json"):
                path = directory / filename
                if path.exists():
                    st.download_button(
                        f"下载 {filename}",
                        path.read_bytes(),
                        file_name=filename,
                        key=f"download-{directory}-{filename}",
                    )
        with st.expander("配置与运行日志"):
            st.json(raw_config)
            log = directory / "worker.log"
            if log.exists():
                st.code(log.read_text(encoding="utf-8", errors="replace")[-6000:])
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    arguments, _ = parser.parse_known_args()
    root = arguments.runs_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    st.set_page_config(page_title="TASS · 小镇社会实验室", page_icon="🏘️", layout="wide")
    st.title("小镇社会实验室")
    st.write("Trustworthy Agent Simulation · AgentScope × Mesa")
    with st.sidebar:
        st.header("新建实验")
        configurations = sorted(
            Path("configs").glob("*.yaml"), key=lambda path: (path.name != "town.yaml", path.name)
        )
        if configurations:
            config_path = st.selectbox(
                "场景配置", configurations, format_func=lambda path: path.name
            )
            mode = st.selectbox("决策方式", ["baseline", "llm"])
            if "run_name" not in st.session_state:
                st.session_state["run_name"] = datetime.now().strftime("town-%Y%m%d-%H%M%S")
            name = st.text_input("运行名称", key="run_name")
            if st.button("启动实验", type="primary"):
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
                    st.error("名称仅可包含字母、数字、下划线和连字符。")
                elif (root / name).exists():
                    st.error("该运行已存在，请使用新名称或恢复已有运行。")
                else:
                    try:
                        config = load_config(config_path)
                        if mode == "llm":
                            from dotenv import load_dotenv

                            load_dotenv()
                            for settings in [config.model, *config.role_models.values()]:
                                resolve_model(settings)
                        launch_worker(root / name, config_path.resolve(), mode)
                        st.session_state["created_run"] = root / name
                        st.session_state["selected_run"] = root / name
                        st.rerun()
                    except (ValueError, OSError) as error:
                        st.error(str(error))
        else:
            st.info("从仓库根目录启动仪表盘以加载示例配置。")
        st.divider()
        st.caption("API 密钥只从本机环境变量或 .env 读取。")
    runs = sorted({path.parent for path in root.rglob("run.sqlite")}, reverse=True)
    created = st.session_state.get("created_run")
    if created and created not in runs:
        runs.insert(0, created)
    if not runs:
        st.info("在左侧选择配置并启动离线实验，或用 tass run 创建运行。")
    else:
        selected = st.selectbox(
            "查看实验",
            runs,
            format_func=lambda path: str(path.relative_to(root)),
            key="selected_run",
        )
        render_run(selected)


if __name__ == "__main__":
    main()
