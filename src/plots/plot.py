from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Generator

import networkx as nx
import numpy as np
from gdpc import interface as INTF
from gdpc import lookup
from numpy import ndarray

from src import env
from src.blocks.block import Block
from src.blocks.collections.block_list import BlockList
from src.simulation.buildings.building_type import BuildingType
from src.utils.coordinates import Coordinates
from src.utils.coordinates import Size
from src.utils.criteria import Criteria


class Plot:
    """Class representing a plot"""

    def __init__(self, x: int, y: int, z: int, size: Size) -> None:
        """Parameterised constructor creating a new plot inside the build area"""
        self.start = Coordinates(x, y, z)
        self.end = Coordinates(x + size.x, 255, z + size.z)
        self.size = size

        self.occupied_coordinates: set[Coordinates] = set()

        self.surface_blocks: dict[Criteria, BlockList] = {}
        self.offset = self.start - env.BUILD_AREA.start, self.end - env.BUILD_AREA.start

        # TODO change center into coordinates
        self.center = self.start.x + self.size.x // 2, self.start.z + self.size.z // 2

        self.steep_factor = 2
        self.steep_map = None
        self.priority_blocks: BlockList | None = None

        self.graph = None

        self.all_roads: set[Coordinates] = set()
        self.roads_infos: dict[str, defaultdict[Coordinates, int]] = {'INNER': defaultdict(int),
                                                                      'MIDDLE': defaultdict(int),
                                                                      'OUTER': defaultdict(int)}
        self.__recently_added_roads = None

    def fill_graph(self):
        self.graph = nx.Graph()
        if self.steep_map is None:
            self.compute_steep_map()

        for block in self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES):
            self.graph.add_node(block.coordinates)

        for coordinates in self.graph.nodes.keys():
            for coord in coordinates.neighbours():
                if coord in self.graph.nodes.keys():
                    # self.graph.add_edge(coordinates, coord, weight=100 + abs(coord.y - coordinates.y) * 10)
                    malus = self.get_steep_map_value(coord)
                    if malus > 20:
                        malus = min(malus * 100, 100_000)
                    self.graph.add_edge(coordinates, coord, weight=100 + malus * 10)

    def equalize_roads(self):
        if len(self.all_roads) < 1:
            return
        roads_y = dict()

        for road in self.all_roads:
            neighbors_blocks = map(lambda coord: self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES).find(coord),
                                   filter(lambda r: r.as_2D() in self.all_roads, road.around_2d(5)))

            neighbors_y = list(map(lambda block: block.coordinates.y, filter(lambda block: block, neighbors_blocks)))

            average_y = sum(neighbors_y) / max(len(neighbors_y), 1)
            roads_y[road.as_2D()] = average_y

        return roads_y

    def build_roads(self, floor_pattern: dict[str, dict[str, float]], slab_pattern=None):
        roads_y = self.equalize_roads()

        roads = []

        # clean above roads
        for road in self.all_roads:
            for i in range(1, 5):
                coordinates = road.with_points(y=int(roads_y[road]) + i)

                if coordinates in self:
                    roads.append(self.get_blocks(Criteria.MOTION_BLOCKING_NO_LEAVES).find(coordinates))
                    INTF.placeBlock(*coordinates, 'air')

        self.remove_trees(BlockList(roads))

        # place blocks
        for key in self.roads_infos.keys():
            for road in self.roads_infos[key]:

                if coordinates not in self:
                    continue

                # Default : place a block
                chose_pattern = floor_pattern
                shift = 0

                # If the average block y is near half :
                if slab_pattern and 0.5 < roads_y[road] - int(roads_y[road]):
                    # place a slab
                    chose_pattern = slab_pattern
                    shift = 1

                INTF.placeBlock(*(road.with_points(y=int(roads_y[road]) + shift)),
                                random.choices(list(chose_pattern[key].keys()), k=1, weights=list(chose_pattern[key].values())))
        INTF.sendBlocks()

    def __add_road_block(self, coordinates: Coordinates, placement: str):

        road_coord = coordinates.as_2D()

        delete = False
        for key in self.roads_infos:
            if key == placement:
                if road_coord not in self.__recently_added_roads[placement]:
                    self.roads_infos[key][road_coord] += 1
                delete = True
            else:
                if road_coord in self.roads_infos[key]:
                    if delete:
                        self.roads_infos[key].pop(road_coord)
                    else:
                        return

        self.__recently_added_roads[placement].add(road_coord)
        self.all_roads.add(road_coord)
        self.occupied_coordinates.add(road_coord)

    def compute_roads(self, start: Coordinates, end: Coordinates):
        if self.graph is None:
            self.fill_graph()
        try:
            path = nx.dijkstra_path(self.graph, start, end)
        except nx.NetworkXException:
            return

        self.__recently_added_roads = {'INNER': set(), 'MIDDLE': set(), 'OUTER': set()}
        for coord in path:
            # INNER PART
            self.__add_road_block(coord, 'INNER')

            # MIDDLE PART
            self.__add_road_block(coord.shift(x=1), 'MIDDLE')
            self.__add_road_block(coord.shift(x=-1), 'MIDDLE')
            self.__add_road_block(coord.shift(z=1), 'MIDDLE')
            self.__add_road_block(coord.shift(z=-1), 'MIDDLE')

            # OUTER PART
            self.__add_road_block(coord.shift(x=1, z=1), 'OUTER')
            self.__add_road_block(coord.shift(x=-1, z=1), 'OUTER')
            self.__add_road_block(coord.shift(x=1, z=-1), 'OUTER')
            self.__add_road_block(coord.shift(x=-1, z=-1), 'OUTER')
            self.__add_road_block(coord.shift(x=2), 'OUTER')
            self.__add_road_block(coord.shift(x=-2), 'OUTER')
            self.__add_road_block(coord.shift(z=2), 'OUTER')
            self.__add_road_block(coord.shift(z=-2), 'OUTER')

        # Update weights to use the roads
        for c1, c2 in zip(path[:-2], path[1:]):
            if self.graph.has_edge(c1, c2):
                self.graph[c1][c2]['weight'] = 10

        INTF.sendBlocks()

    @ staticmethod
    def from_coordinates(start: Coordinates, end: Coordinates) -> Plot:
        """Return a new plot created from the given start and end coordinates"""
        return Plot(*start, Size.from_coordinates(start, end))

    def update(self) -> None:
        """Update the env.WORLD slice and most importantly the heightmaps"""
        env.update_world_slice()
        self.surface_blocks.clear()

    @ staticmethod
    def _delta_sum(values: list, base: int) -> int:
        return sum(abs(base - v) for v in values)

    def flat_heightmap_to_plot_block(self, index: int) -> Block | None:
        surface = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES)

        span = self.steep_factor

        side_length = self.size.x - 2 * span
        x = index // side_length
        z = index - side_length * x

        return surface.find(self.start.shift(x + span, 0, z + span))

    def compute_steep_map(self):
        span = self.steep_factor

        heightmap: np.ndarray = self.get_heightmap(Criteria.MOTION_BLOCKING_NO_TREES)

        steep = np.empty(shape=(self.size.x - 2 * span, self.size.z - 2 * span))
        for i in range(span, self.size.x - span):
            for j in range(span, self.size.z - span):
                block = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES).find(self.start.shift(i, 0, j))
                if block.is_one_of(('water',)):
                    steep[i - span, j - span] = 100_000_000
                else:
                    steep[i - span, j - span] = self._delta_sum(
                        heightmap[i - span: i + 1 + span, j - span: j + 1 + span].flatten(), heightmap[i, j])

        self.steep_map = steep.flatten()

        amount_of_prio = int((10 / 100) * self.steep_map.size)

        prio = np.argpartition(self.steep_map, amount_of_prio)[:amount_of_prio]
        blocks = []
        for p in prio:
            block = self.flat_heightmap_to_plot_block(p)
            if block and block not in self.occupied_coordinates:
                blocks.append(block)
        self.priority_blocks = BlockList(blocks)

    def visualize_roads(self, y_offset: int = 0):
        colors = ('lime', 'white', 'pink', 'yellow', 'orange', 'red', 'magenta', 'purple', 'black')
        materials = ('concrete', 'wool', 'stained_glass')
        ys = self.equalize_roads()
        for i, key in enumerate(self.roads_infos):
            for road in self.roads_infos[key]:
                block = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES).find(
                    road)  # to be sure that we are in the plot
                if block:
                    INTF.placeBlock(*(road.with_points(y=ys[road] + y_offset)),
                                    colors[min(self.roads_infos[key][road], len(colors)) - 1] + '_' + materials[i])

        INTF.sendBlocks()

    def visualize_occupied_area(self):
        for coord in self.occupied_coordinates:
            block = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES).find(coord)
            if block:
                INTF.placeBlock(*(block.coordinates.shift(y=1)), 'red_stained_glass')
        INTF.sendBlocks()

    def visualize_graph(self):
        colors = ('lime', 'white', 'pink', 'yellow', 'orange', 'red', 'magenta', 'purple', 'black')
        for coord in self.graph.nodes():
            weights = list(map(lambda edge: self.graph[edge[0]][edge[1]]['weight'], self.graph.edges(coord)))
            if len(weights) == 0:
                chose_color = 'blue'
            else:
                coord_access_value = min(weights)
                chose_color = 'black'
                if coord_access_value < 50:
                    chose_color = colors[0]
                elif coord_access_value < 110:
                    continue  # 'default' value, don't show
                elif coord_access_value < 150:
                    chose_color = colors[2]
            INTF.placeBlock(*(coord.shift(y=1)), chose_color + '_stained_glass')
        INTF.sendBlocks()

    def visualize_steep_map(self):
        span = self.steep_factor
        colors = ('lime', 'white', 'pink', 'yellow', 'orange', 'red', 'magenta', 'purple', 'black')
        for i, value in enumerate(self.steep_map):
            block = self.flat_heightmap_to_plot_block(i, span)
            if block:
                INTF.placeBlock(*block.coordinates, colors[min(int(value // span), 8)] + '_stained_glass')
        INTF.sendBlocks()

    def visualize(self, ground: str = 'orange_wool', criteria: Criteria = Criteria.MOTION_BLOCKING_NO_TREES) -> None:
        """Change the blocks at the surface of the plot to visualize it"""
        for block in self.get_blocks(criteria):
            INTF.placeBlock(*block.coordinates, ground)
        INTF.sendBlocks()

    def get_block_at(self, x: int, y: int, z: int) -> Block:
        """Return the block found at the given x, y, z coordinates in the env.WORLD"""
        try:
            name = env.WORLD.getBlockAt(x, y, z)
            return Block.deserialize(name, Coordinates(x, y, z))
        except IndexError:
            return Block('out of bound', None)

    def get_heightmap(self, criteria: Criteria) -> ndarray:
        """Return the desired heightmap of the given type"""
        # Add our custom
        if Criteria.MOTION_BLOCKING_NO_TREES not in env.WORLD.heightmaps:
            env.WORLD.heightmaps[Criteria.MOTION_BLOCKING_NO_TREES.name] = self.__get_heightmap_no_trees()

        if criteria.name in env.WORLD.heightmaps.keys():
            return env.WORLD.heightmaps[criteria.name][self.offset[0].x:self.offset[1].x,
                                                       self.offset[0].z:self.offset[1].z]

        raise Exception(f'Invalid criteria: {criteria}')

    def get_blocks(self, criteria: Criteria) -> BlockList:
        """Return a list of the blocks at the surface of the plot, using the given criteria"""

        if criteria in self.surface_blocks.keys():
            return self.surface_blocks[criteria]

        surface = []
        heightmap = self.get_heightmap(criteria)

        for x, rest in enumerate(heightmap):
            for z, h in enumerate(rest):
                coordinates = Coordinates(self.start.x + x, h - 1, self.start.z + z)
                surface.append(self.get_block_at(*coordinates))

        self.surface_blocks[criteria] = BlockList(surface)
        return self.surface_blocks[criteria]

    def __get_heightmap_no_trees(self) -> np.ndarray:
        """Return a list of block representing a heightmap without trees

        It is not perfect as sometimes, there can be flower or grass or other blocks between the ground and the '
        floating' logs, but it is good enough for our use"""
        heightmap = np.copy(env.WORLD.heightmaps[Criteria.MOTION_BLOCKING_NO_LEAVES.name])

        for x, rest in enumerate(heightmap):
            for z, h in enumerate(rest):
                base_coord = Coordinates(env.BUILD_AREA.start.x + x, h - 1, env.BUILD_AREA.start.z + z)

                ground_coord = None
                # To get to the last block until the ground
                for ground_coord in self.__yield_until_ground(base_coord):
                    pass
                if ground_coord:
                    heightmap[x, z] = ground_coord.y

        return heightmap

    def get_subplot(self, size: Size, padding: int = 5, max_score: int = None, occupy_coord: bool = True,
                    building_specs: str | BuildingType = None, city_buildings: list = None) -> Plot | None:
        """Return the best coordinates to place a building of a certain size, minimizing its score"""
        if max_score is None:
            # Auto define max score
            max_score = size.x * size.z

        if self.graph is None:
            self.fill_graph()

        # TODO add .lower_than(max_height=200)

        surface = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES)
        surface = surface.without('water').not_inside(self.occupied_coordinates)

        random_blocks = int(len(surface) * (10 / 100))

        blocks_to_check = surface.random_elements(random_blocks)

        if self.priority_blocks is None:
            self.compute_steep_map()

            if env.DEBUG:
                self.visualize_steep_map()

        blocks_to_check = self.priority_blocks + blocks_to_check
        if env.DEBUG:
            print(f'Checking : {len(blocks_to_check)} blocks ({len(self.priority_blocks)} from prio)')

        # DEBUG
        if env.DEBUG and False:
            colors = list(lookup.COLORS)
            random.shuffle(colors)
            for block in surface:
                INTF.placeBlock(*block.coordinates, colors[0] + '_wool')

            INTF.sendBlocks()

        # >Get the minimal score in the coordinate list
        min_score = max_score

        for block in blocks_to_check:
            block_score = self.__get_score(block.coordinates, surface, size, max_score, building_specs=building_specs,
                                           city_buildings=city_buildings)

            if block_score < min_score:
                best_coordinates = block.coordinates
                min_score = block_score

        if env.DEBUG:
            print(f'Best score : {min_score}')

        if min_score >= max_score:
            return None

        sub_plot = Plot(*best_coordinates, size=size)

        if occupy_coord:
            for coordinates in sub_plot.surface(8 if building_specs is BuildingType.FARM else padding):
                self.occupied_coordinates.add(coordinates.as_2D())

                block = self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES).find(coordinates)
                if block and block.coordinates.as_2D() not in self.all_roads:
                    for edges in self.graph.edges(block.coordinates):
                        self.graph.add_edge(*edges, weight=100_000_000)

        if env.DEBUG:
            self.visualize_roads(10)
            self.visualize_graph()

        return sub_plot

    def __get_score(self, coordinates: Coordinates, surface: BlockList, size: Size, max_score: int,
                    building_specs: str | BuildingType = None, city_buildings: list = None) -> float:
        """Return a score evaluating the fitness of a building in an area.
            The lower the score, the better it fits

            Score is calculated as follows :
            malus depending on the distance from the center of the area +
            Sum of all differences in the y coordinate
            """
        # apply malus to score depending on the distance to the 'center'

        # TODO Maybe improve this notation, quite not beautiful, set center as a coordinate ?
        # Would be great
        center = Coordinates(self.center[0], 0, self.center[1])
        score = coordinates.as_2D().distance(center) * .1

        # Score = sum of difference between the first point's altitude and the other
        for x in range(size.x):
            for z in range(size.z):
                current_coord = coordinates.shift(x, 0, z)
                current_block = surface.find(current_coord)

                if not current_block or current_block.coordinates in self.occupied_coordinates:
                    return 100_000_000

                # putting foundation isn't a problem compared to digging in the terrain, so we apply a
                # worsening factor to digging
                to_add = coordinates.y - current_block.coordinates.y
                # placing foundation
                if to_add > 0:
                    score += int(to_add * .8)
                # digging (bad)
                else:
                    score += abs(to_add) * 3

                # Return earlier if score is already too bad
                if score >= max_score:
                    return score

        # And now modifications for specials buildings
        relation = env.RELATIONS.get_building_relation(building_specs)
        score_modif = 0
        if relation and city_buildings:
            score_modif = max(list(map(lambda build: relation.get_building_value(build.name), filter(lambda b: b.plot.start.distance(coordinates) < 50, city_buildings))) + [0])

        return score + score_modif

    def remove_trees(self, surface: BlockList = None) -> None:
        """Remove all plants at the surface of the current plot"""
        pattern = ('log', 'bush', 'mushroom')
        if surface is None:
            surface = self.get_blocks(Criteria.MOTION_BLOCKING_NO_LEAVES)

        amount = 0
        unwanted_blocks = surface.filter(pattern).to_set()

        if env.DEBUG:
            print(f'\n=> Removing trees on plot at {self.start} with size {self.size}')

        while unwanted_blocks:
            block = unwanted_blocks.pop()
            for coord in self.__yield_until_ground(block.coordinates):
                INTF.placeBlock(*coord, 'minecraft:air')
                amount += 1

        INTF.sendBlocks()
        if env.DEBUG:
            print(f'=> Deleted {amount} blocs\n')
        # self.update()

    def __yield_until_ground(self, coordinates: Coordinates):
        """Yield the coordinates """
        current_coord: Coordinates = coordinates

        while self.get_block_at(*current_coord).is_one_of(('air', 'leaves', 'log', 'vine')):
            yield current_coord
            current_coord = current_coord.shift(0, -1, 0)

    def build_foundation(self, block: str = None) -> None:
        """Build the foundations under the house"""

        blocks = ('stone_bricks', 'diorite', 'cobblestone')
        weights = (75, 15, 10)

        for coord in self.__iterate_over_air(self.start.y):
            if block is None:
                block = random.choices(blocks, weights)
            INTF.placeBlock(*coord, block)
        INTF.sendBlocks()

    def __iterate_over_air(self, max_y: int) -> Coordinates:
        """"""
        for block in self.get_blocks(Criteria.MOTION_BLOCKING_NO_TREES):
            for new_y in range(block.coordinates.y, max_y):
                yield block.coordinates.with_points(y=new_y)

    def __contains__(self, coordinates: Coordinates) -> bool:
        """Return true if the current plot contains the given coordinates"""
        return self.start.x <= coordinates.x < self.end.x and \
            self.start.y <= coordinates.y <= self.end.y and \
            self.start.z <= coordinates.z < self.end.z

    def surface(self, padding: int = 0) -> Generator[Coordinates]:
        """Return a generator over the coordinates of the current plot"""
        for x in range(-padding, self.size.x + padding):
            for z in range(-padding, self.size.z + padding):
                yield self.start.shift(x, 0, z)

    def get_steep_map_value(self, coord: Coordinates) -> int:
        if self.steep_map is None:
            self.compute_steep_map()

        steep_map_size = self.size.x - self.steep_factor * 2, self.size.z - self.steep_factor * 2
        i, j = (coord - self.start).xz
        i = min(max(i - self.steep_factor, 0), steep_map_size[0] - 1)
        j = min(max(j - self.steep_factor, 0), steep_map_size[1] - 1)
        return self.steep_map[j + i * steep_map_size[1]]

