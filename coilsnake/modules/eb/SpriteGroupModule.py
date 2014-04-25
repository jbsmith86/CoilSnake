import yaml

from PIL import Image

from coilsnake.exceptions.common.exceptions import CoilSnakeError
from coilsnake.model.common.blocks import Block
from coilsnake.model.eb.palettes import EbPalette
from coilsnake.model.eb.sprites import SpriteGroup, SPRITE_SIZES
from coilsnake.model.eb.table import eb_table_from_offset
from coilsnake.modules.eb.EbModule import EbModule
from coilsnake.util.common.yml import replace_field_in_yml
from coilsnake.util.eb.pointer import from_snes_address, to_snes_address


GROUP_POINTER_TABLE_OFFSET = 0xef133f
PALETTE_TABLE_OFFSET = 0xc30000


class SpriteGroupModule(EbModule):
    NAME = "Sprite Groups"
    FREE_RANGES = [(0x2f1a7f, 0x2f4a3f),
                   (0x110000, 0x11ffff),
                   (0x120000, 0x12ffff),
                   (0x130000, 0x13ffff),
                   (0x140000, 0x14ffff),
                   (0x150000, 0x154fff)]

    def __init__(self):
        super(SpriteGroupModule, self).__init__()
        self.group_pointer_table = eb_table_from_offset(offset=GROUP_POINTER_TABLE_OFFSET)
        self.palette_table = eb_table_from_offset(offset=PALETTE_TABLE_OFFSET)
        self.groups = None

    def read_from_rom(self, rom):
        self.group_pointer_table.from_block(rom, from_snes_address(GROUP_POINTER_TABLE_OFFSET))
        self.palette_table.from_block(rom, from_snes_address(PALETTE_TABLE_OFFSET))

        # Load the sprite groups
        self.groups = []
        for i in range(self.group_pointer_table.num_rows):
            # Note: this assumes that the SPT is written contiguously
            num_sprites = 8
            # Assume that the last group only has 8 sprites
            if i < self.group_pointer_table.num_rows - 1:
                num_sprites = (self.group_pointer_table[i + 1][0] - self.group_pointer_table[i][0] - 9) / 2

            group = SpriteGroup(num_sprites)
            group.from_block(rom, from_snes_address(self.group_pointer_table[i][0]))
            self.groups.append(group)

    def write_to_project(self, resource_open):
        # Write the palettes
        with resource_open("sprite_group_palettes", "yml") as f:
            self.palette_table.to_yml_file(f)

        out = {}
        for i, group in enumerate(self.groups):
            out[i] = group.yml_rep()
            image = group.image(self.palette_table[group.palette][0])
            with resource_open("SpriteGroups/" + str(i).zfill(3), 'png') as image_file:
                image.save(image_file, 'png', transparency=0)
            del image
        with resource_open("sprite_groups", "yml") as f:
            yaml.dump(out, f, Dumper=yaml.CSafeDumper)

    def read_from_project(self, resource_open):
        with resource_open("sprite_group_palettes", "yml") as f:
            self.palette_table.from_yml_file(f)

        with resource_open("sprite_groups", "yml") as f:
            input = yaml.load(f, Loader=yaml.CSafeLoader)
            num_groups = len(input)
            self.groups = []
            for i in range(num_groups):
                group = SpriteGroup(16)
                group.from_yml_rep(input[i])
                try:
                    image = Image.open(resource_open("SpriteGroups/" + str(i).zfill(3), "png"))
                except IOError:
                    raise CoilSnakeError("Could not open image for Sprite Group #" + str(i))

                if image.mode != 'P':
                    raise CoilSnakeError("SpriteGroups/" + str(i).zfill(3) + " is not an indexed PNG.")

                group.from_image(image)
                palette = EbPalette(1, 16)
                palette.from_image(image)
                del image
                self.groups.append(group)

                # Assign the palette number to the sprite
                for j in range(8):
                    if palette.list()[3:] == self.palette_table[j][0].list()[3:]:
                        group.palette = j
                        break
                else:
                    # Error, this image uses an invalid palette
                    for k in range(8):
                        print k, ":", self.palette_table[k, 0]
                    raise CoilSnakeError("Sprite Group #" + str(i) + " uses an invalid palette: "
                                         + palette.list()[0][1:])

    def write_to_rom(self, rom):
        with Block(size=sum(x.block_size() for x in self.groups)) as block:
            offset = 0
            # Write all the groups to the block, and sprites to rom
            for i, group in enumerate(self.groups):
                group.write_sprites_to_free(rom)
                group.to_block(block, offset)
                self.group_pointer_table[i] = [offset]
                offset += group.block_size()
            # Write the block to rom and correct the group pointers
            address = to_snes_address(rom.allocate(data=block))
            for i in range(self.group_pointer_table.num_rows):
                self.group_pointer_table[i][0] += address

        self.group_pointer_table.to_block(block=rom, offset=from_snes_address(GROUP_POINTER_TABLE_OFFSET))
        self.palette_table.to_block(block=rom, offset=from_snes_address(PALETTE_TABLE_OFFSET))

    def upgrade_project(self, old_version, new_version, rom, resource_open_r, resource_open_w, resource_delete):
        if old_version == new_version:
            return
        elif old_version == 2:
            replace_field_in_yml(resource_name="sprite_groups",
                                 resource_open_r=resource_open_r,
                                 resource_open_w=resource_open_w,
                                 key="Unknown A",
                                 new_key="Size",
                                 value_map=dict(enumerate(SPRITE_SIZES)))
            replace_field_in_yml(resource_name="sprite_groups",
                                 resource_open_r=resource_open_r,
                                 resource_open_w=resource_open_w,
                                 key="Unknown B",
                                 new_key="Collision Settings")
            self.upgrade_project(old_version + 1, new_version, rom, resource_open_r, resource_open_w, resource_delete)
        else:
            self.upgrade_project(old_version + 1, new_version, rom, resource_open_r, resource_open_w, resource_delete)
