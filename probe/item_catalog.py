"""Early survival values for loose items. Other pickupable items remain eligible nearby."""

# prefab: (Chinese label, desired inventory count, priority, pursuit radius)
ITEM_CATALOG = {
    "flint": ("燧石", 6, 6, 12),
    "rocks": ("石头", 8, 4, 12),
    "goldnugget": ("金块", 3, 5, 12),
    "cutgrass": ("草", 16, 6, 12),
    "twigs": ("树枝", 16, 6, 12),
    "log": ("木头", 6, 4, 10),
    "berries": ("浆果", 8, 4, 8),
    "berries_juicy": ("多汁浆果", 8, 4, 8),
    "carrot": ("胡萝卜", 8, 4, 8),
    "seeds": ("种子", 8, 2, 6),
    "smallmeat": ("小肉", 2, 3, 8),
    "spear": ("长矛", 1, 8, 24),
    "hambat": ("火腿棍", 1, 8, 24),
    "armorwood": ("木甲", 1, 8, 20),
    "armorgrass": ("草甲", 1, 6, 12),
    "footballhat": ("猪皮头盔", 1, 8, 20),
    "backpack": ("背包", 1, 8, 24),
    "lantern": ("提灯", 1, 9, 24),
    "minerhat": ("矿工帽", 1, 9, 24),
    "torch": ("火炬", 2, 6, 12),
    "axe": ("斧头", 1, 5, 12),
    "pickaxe": ("鹤嘴锄", 1, 6, 12),
    "shovel": ("铲子", 1, 3, 8),
    "hammer": ("锤子", 1, 3, 8),
    "beefalowool": ("牛毛", 12, 4, 14),
    "beefalohorn": ("牛角", 1, 7, 20),
    "gears": ("齿轮", 4, 8, 24),
    "pigskin": ("猪皮", 6, 6, 16),
    "silk": ("蛛丝", 10, 5, 14),
    "spidergland": ("蜘蛛腺体", 5, 5, 14),
    "rope": ("绳子", 8, 4, 12),
    "boards": ("木板", 8, 4, 12),
    "cutstone": ("石砖", 8, 6, 12),
    "charcoal": ("木炭", 8, 4, 12),
    "manure": ("粪便", 8, 3, 8),
    "nitre": ("硝石", 6, 3, 8),
    "marble": ("大理石", 6, 4, 12),
    "pinecone": ("松果", 8, 2, 6),
    "acorn": ("桦栗果", 8, 2, 6),
    "petals": ("花瓣", 6, 1, 3),
    "red_cap": ("红蘑菇", 4, 2, 6),
    "green_cap": ("绿蘑菇", 4, 3, 8),
    "blue_cap": ("蓝蘑菇", 4, 3, 8),
}


def loose_item_offer(prefab, owned, free_slots, distance):
    if free_slots <= 0:
        return None
    label, target, priority, radius = ITEM_CATALOG.get(prefab, (prefab, 1, 1, 3))
    if owned >= target:
        return None
    if free_slots <= 3 and priority < 6:
        return None
    if distance > radius:
        return None
    return priority, label
