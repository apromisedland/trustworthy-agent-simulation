import pytest

from tass.types import Action, Decision
from tass.world import ActionRejected


def create_contract(scenario, world, quantity=2):
    scenario.apply(world, "shop_00", Action(kind="offer", quantity=quantity, amount=100))
    offer_id = next(reversed(world.offers))
    scenario.apply(
        world, "resident_00", Action(kind="accept_offer", target=offer_id, quantity=quantity)
    )
    return next(reversed(world.contracts))


def test_atomic_escrow_and_single_settlement(town):
    scenario, world = town
    buyer = world.state("resident_00")
    seller = world.state("shop_00")
    before = (buyer.cash, seller.cash, buyer.inventory["food"], seller.inventory["food"])
    contract_id = create_contract(scenario, world)
    assert buyer.cash == before[0] - 200
    assert seller.cash == before[1]
    assert world.escrow == 200
    assert seller.inventory["food"] == before[3] - 2
    world.assert_invariants()
    with pytest.raises(ActionRejected, match="Unauthorized"):
        scenario.apply(world, "shop_01", Action(kind="deliver", target=contract_id))
    scenario.apply(world, "shop_00", Action(kind="deliver", target=contract_id))
    assert seller.cash == before[1] + 200
    assert buyer.inventory["food"] == before[2] + 2
    assert world.escrow == 0
    with pytest.raises(ActionRejected, match="settled"):
        scenario.apply(world, "shop_00", Action(kind="deliver", target=contract_id))
    world.assert_invariants()


def test_expiry_refunds_goods_and_money(town):
    scenario, world = town
    cash = world.state("resident_00").cash
    stock = world.state("shop_00").inventory["food"]
    contract_id = create_contract(scenario, world)
    world.tick = world.contracts[contract_id].deadline + 1
    scenario.begin_tick(world)
    assert world.contracts[contract_id].status == "expired"
    assert world.state("resident_00").cash == cash
    assert world.state("shop_00").inventory["food"] == stock
    assert world.escrow == 0
    scenario.begin_tick(world)
    assert world.state("resident_00").cash == cash
    world.assert_invariants()


def test_insufficient_funds_does_not_change_inventory(town):
    scenario, world = town
    scenario.apply(world, "shop_00", Action(kind="offer", quantity=2, amount=100000))
    before = world.snapshot()
    with pytest.raises(ActionRejected, match="Insufficient"):
        scenario.apply(
            world, "resident_00", Action(kind="accept_offer", target=next(iter(world.offers)))
        )
    assert world.snapshot() == before


def test_same_stock_cannot_be_sold_twice(town):
    scenario, world = town
    stock = world.state("shop_00").inventory["food"]
    for _ in range(2):
        scenario.apply(world, "shop_00", Action(kind="offer", quantity=stock, amount=1))
    offers = list(world.offers)
    scenario.apply(
        world, "resident_00", Action(kind="accept_offer", target=offers[0], quantity=stock)
    )
    with pytest.raises(ActionRejected, match="unavailable"):
        scenario.apply(
            world, "resident_01", Action(kind="accept_offer", target=offers[1], quantity=stock)
        )
    world.assert_invariants()


def test_payroll_requires_work_and_is_once_per_tick(town):
    scenario, world = town
    resident = world.state("resident_00")
    employer = world.state(resident.employer)
    with pytest.raises(ActionRejected, match="workplace"):
        scenario.apply(world, "resident_00", Action(kind="work"))
    world.space.move_agent(world.actors["resident_00"], employer.home)
    resident.location = employer.home
    cash = resident.cash
    scenario.apply(world, "resident_00", Action(kind="work"))
    assert resident.cash == cash + world.config.resources.wage
    with pytest.raises(ActionRejected, match="already"):
        scenario.apply(world, "resident_00", Action(kind="work"))
    world.assert_invariants()


def test_finite_treasury_equal_subsidy(config):
    from tass.scenarios.town import TownScenario

    config.resources.treasury = 12
    config.policies.subsidy = 100
    config.policies.subsidy_day = 0
    scenario = TownScenario()
    world = scenario.build_world(config)
    before = {key: actor.state.cash for key, actor in world.actors.items()}
    scenario.begin_tick(world)
    assert world.treasury == 2
    assert world.policy_spending == 10
    assert all(
        actor.state.cash - before[key] == 2
        for key, actor in world.actors.items()
        if actor.state.profile.role == "resident"
    )
    world.assert_invariants()


def test_unauthorized_action_rejected_by_dispatcher(town):
    scenario, world = town
    decisions = {identifier: Decision() for identifier in world.actors}
    decisions["resident_00"] = Decision(actions=[Action(kind="produce", quantity=100)])
    scenario.resolve(world, decisions)
    assert any(event.kind == "action_rejected" for event in world.events)
    assert not world.goods_created
