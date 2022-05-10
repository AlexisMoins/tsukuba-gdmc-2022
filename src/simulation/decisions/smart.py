import random

from src.plots.plot import Plot
from src.simulation.buildings.building import Building
from src.simulation.city import City
from src.simulation.decisions.decision_maker import DecisionMaker
from src.utils.action_type import ActionType
from src.utils.coordinates import Coordinates
from src.utils.coordinates import Size


class SmartDecisionMaker(DecisionMaker):

    def __init__(self, plot: Plot):
        super().__init__()
        self.plot = plot
        self.chose_rotation = 0
        self.chose_coordinates = None
        self.action_choose: Building | None = None
        self.city: City = None

    def choose_building(self, possible_actions: list[Building], rotation: int) -> tuple[Building, Plot] | tuple[None, None]:
        """"""

        # No point in computing anything if there is one option
        if len(possible_actions) == 1:
            return possible_actions[0]

        city_stats = [(self.city.number_of_beds, ActionType.BED), (self.city.food_production, ActionType.FOOD),
                      (self.city.work_production, ActionType.WORK)]

        next_action_type = min(city_stats, key=lambda item: item[0])[1]
        priority_actions: list[Building] = []

        for building in possible_actions:
            if building is not None and building.properties.action_type == next_action_type:
                priority_actions.append(building)

        if not priority_actions:
            return None, None

        building = random.choice(priority_actions)
        plot = self.plot.get_subplot(building.get_size(rotation), building_specs=building.name,
                                     city_buildings=self.city.buildings)

        if plot is not None:
            return building, plot

        return None, None

    def get_rotation(self) -> int:
        # TODO : Implement brain here too
        orientation = [0, 90, 180, 270]
        self.chose_rotation = 0
        return random.choice(orientation)