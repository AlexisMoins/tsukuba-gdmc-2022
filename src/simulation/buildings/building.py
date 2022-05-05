from __future__ import annotations

import random
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from colorama import Fore
from gdpc import interface as INTERFACE
from gdpc import toolbox
from gdpc import toolbox as TOOLBOX

from src import env
from src.blocks.block import Block
from src.blocks.collections import palette
from src.blocks.collections.block_list import BlockList
from src.blocks.collections.palette import Palette
from src.blocks.structure import Structure
from src.plots.plot import Plot
from src.simulation.buildings.building_type import BuildingType
from src.utils.action_type import ActionType
from src.utils.coordinates import Coordinates
from src.utils.coordinates import Size


@dataclass(kw_only=True)
class BuildingProperties:
    """Class representing the properties of a building"""
    cost: int
    building_type: BuildingType
    action_type: ActionType
    number_of_beds: int = 0
    work_production: float = 0
    food_production: float = 0


class Building:
    """Class representing a list of blocks (structure) on a given plot"""

    def __init__(self, name: str, properties: BuildingProperties, structure: Structure, is_extension: bool):
        """Parameterised constructor creating a new building"""
        self.name = name
        self.properties = replace(properties)  # Return a copy of the dataclass
        self.__structure = structure
        self.old_blocks: dict[Block, Block] = {}
        self.is_extension = is_extension

        self.plot: Plot = None
        self.rotation: int = None
        self.blocks: BlockList = None
        self.entrances: BlockList = None

    @staticmethod
    def deserialize(building: dict[str, Any]) -> Building:
        """Return a new building deserialized from the given dictionary"""
        properties = {key.replace(' ', '_'): value
                      for key, value in building['properties'].items()}

        action_type = ActionType[building['action'].upper()]
        building_type = BuildingType[building['type'].upper()]
        properties = BuildingProperties(**properties,
                                        action_type=action_type, building_type=building_type)

        structure = Structure.parse_nbt_file(building['path'])
        return Building(building['name'], properties, structure, is_extension=('extensions' in building['path']))

    def get_size(self, rotation: int) -> Size:
        """Return the size of the building considering the given rotation"""
        return self.__structure.get_size(rotation)

    def build(self, plot: Plot, rotation: int):
        """Build the current building onto the building's plot"""
        self.plot = plot
        self.rotation = rotation

        self.blocks = self.__structure.get_blocks(plot.start, rotation)

        # Apply palette
        if self.properties.building_type in env.ALL_PALETTES:
            self.__randomize_building(dict(env.ALL_PALETTES[self.properties.building_type]))

        self.entrances = self.blocks.filter('emerald')
        for block in self.blocks:
            INTERFACE.placeBlock(*block.coordinates, block.full_name)

        self.__place_sign()
        INTERFACE.sendBlocks()

    def __place_sign(self):
        """Place a sign indicating informations about the building"""
        if not self.entrances:
            return None

        sign_coord = self.entrances[0].coordinates.shift(y=1)
        if env.DEBUG:
            self.build_sign_in_world(sign_coord, text1=self.name, text2=f'rotation : {self.rotation}')
        else:
            # TODO : Generate name here
            self.build_sign_in_world(sign_coord, text1=self.name)

        for entrance in self.entrances:
            neighbours = [self.plot.get_block_at(*coordinates)
                          for coordinates in entrance.neighbouring_coordinates()]

            block_name = BlockList(neighbours).without(
                ('air', 'grass', 'sand', 'water')).most_common

            if block_name is not None:
                INTERFACE.placeBlock(*entrance.coordinates, block_name)

    def grow_old(self, amount: int) -> None:
        """Make a building grow old"""

        # ensure it stays between 0 and 100
        amount = abs(amount) % 100
        sample: list[Block] = random.sample(self.blocks.without('air'), amount * len(self.blocks.without('air')) // 100)

        for block in sample:

            materials = {
                'cobblestone': ('mossy_cobblestone', True),
                'mossy_stone': ('cracked_stone', True),
                'stone': ('mossy_stone', True),
                'planks': ('stairs', False)
            }

            replacement = block.replace_first(materials)

            if replacement is not block and Block.exists(replacement.name):
                if 'stairs' in replacement.name:
                    facing = random.choice(['north', 'east', 'south', 'west'])
                    half = random.choice(['top', 'bottom'])
                    shape = random.choice(['inner_left', 'inner_right', 'outer_left', 'outer_right', 'straight'])
                    replacement = replace(replacement, properties={'facing': facing, 'half': half, 'shape': shape})
                self.old_blocks[block] = replacement

            else:
                population = (block.name, 'oak_leaves', 'cobweb', 'air')
                weights = (60, 30, 7, 3)

                name = random.choices(population, weights, k=1)

                if name == block.name:
                    continue

                replacement = Block(name[0], block.coordinates, properties={
                                    'persistent': 'true'} if name[0] == 'oak_leaves' else {})
                self.old_blocks[block] = replacement

            INTERFACE.placeBlock(*replacement.coordinates, replacement.full_name)

        INTERFACE.sendBlocks()

    def build_sign_in_world(self, coord: Coordinates, text1: str = "", text2: str = "", text3: str = "",
                            text4: str = ""):
        x, y, z = coord

        INTERFACE.placeBlock(x, y, z, "oak_sign")
        INTERFACE.sendBlocks()

        data = "{" + f'Text1:\'{{"text":"{text1}"}}\','
        data += f'Text2:\'{{"text":"{text2}"}}\','
        data += f'Text3:\'{{"text":"{text3}"}}\','
        data += f'Text4:\'{{"text":"{text4}"}}\'' + "}"
        INTERFACE.runCommand(f"data merge block {x} {y} {z} {data}")

    def __str__(self) -> str:
        """Return the string representation of the current building"""
        return f'{Fore.MAGENTA}{self.name}{Fore.WHITE}'

    def __randomize_building(self, palettes: dict[str, Palette | list]):
        """Create a new block list with modified blocks according to given palettes"""
        new_block_list = []

        # prepare palettes
        for key in palettes:
            if isinstance(palettes[key], list):
                palettes[key] = palette.OneBlockPalette(palettes[key])

        for b in self.blocks:
            current_name = b.name.replace('minecraft:', '')
            if current_name in palettes:
                new_block_list.append(b.with_name(palettes[current_name].get_block_name()))
            else:
                new_block_list.append(b)

        self.blocks = BlockList(new_block_list)
