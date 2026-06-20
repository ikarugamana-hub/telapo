COLLECTION_EXCLUDED_PREFECTURES = {"沖縄県"}

ORDINANCE_DESIGNATED_PREFECTURES = {
    "北海道",
    "宮城県",
    "埼玉県",
    "千葉県",
    "神奈川県",
    "新潟県",
    "静岡県",
    "愛知県",
    "京都府",
    "大阪府",
    "兵庫県",
    "岡山県",
    "広島県",
    "福岡県",
    "熊本県",
}

PREFECTURE_BOOST_BASELINES = {
    "北海道": 10000,
    "青森県": 10000,
    "岩手県": 10000,
    "宮城県": 10000,
    "秋田県": 10000,
    "山形県": 10000,
    "福島県": 10000,
    "茨城県": 10000,
    "栃木県": 10000,
    "群馬県": 10000,
    "埼玉県": 10000,
    "千葉県": 10000,
    "東京都": 10000,
    "神奈川県": 10000,
    "新潟県": 10100,
    "富山県": 10000,
    "石川県": 12484,
    "福井県": 10000,
    "山梨県": 10000,
    "長野県": 10000,
    "岐阜県": 10000,
    "静岡県": 10000,
    "愛知県": 10000,
    "三重県": 10000,
    "滋賀県": 10000,
    "京都府": 10000,
    "大阪府": 10000,
    "兵庫県": 10000,
    "奈良県": 10000,
    "和歌山県": 10000,
    "鳥取県": 6963,
    "島根県": 8677,
    "岡山県": 10000,
    "広島県": 10000,
    "山口県": 10000,
    "徳島県": 10000,
    "香川県": 10000,
    "愛媛県": 10000,
    "高知県": 9261,
    "福岡県": 10000,
    "佐賀県": 10000,
    "長崎県": 10000,
    "熊本県": 10000,
    "大分県": 10000,
    "宮崎県": 10000,
    "鹿児島県": 10000,
}

NORMAL_PREFECTURE_ADDITION = 5_000
ORDINANCE_PREFECTURE_TARGET = 20_000

REGIONAL_COLLECTION_TARGETS = {
    "関東エリア": {
        "prefectures": ("東京都", "神奈川県", "埼玉県", "千葉県"),
        "target": 800_000,
    },
    "関西エリア": {
        "prefectures": ("大阪府", "京都府", "兵庫県"),
        "target": 100_000,
    },
    "名古屋エリア": {
        "prefectures": ("愛知県",),
        "target": 100_000,
    },
}

PREFECTURE_TO_REGION = {
    prefecture: region_name
    for region_name, config in REGIONAL_COLLECTION_TARGETS.items()
    for prefecture in config["prefectures"]
}


def get_collection_scope(prefecture):
    region_name = PREFECTURE_TO_REGION.get(prefecture)
    if region_name:
        config = REGIONAL_COLLECTION_TARGETS[region_name]
        return {
            "key": region_name,
            "name": region_name,
            "prefectures": config["prefectures"],
            "target": config["target"],
            "target_type": "地域合計",
        }

    baseline = PREFECTURE_BOOST_BASELINES.get(prefecture, 0)
    if prefecture in ORDINANCE_DESIGNATED_PREFECTURES:
        target = max(baseline, ORDINANCE_PREFECTURE_TARGET)
        target_type = "政令指定都市県"
    else:
        target = baseline + NORMAL_PREFECTURE_ADDITION
        target_type = "追加5000県"
    return {
        "key": prefecture,
        "name": prefecture,
        "prefectures": (prefecture,),
        "target": target,
        "target_type": target_type,
    }


def iter_collection_scopes(prefectures):
    seen = set()
    for prefecture in prefectures:
        if prefecture in COLLECTION_EXCLUDED_PREFECTURES:
            continue
        scope = get_collection_scope(prefecture)
        if scope["key"] in seen:
            continue
        seen.add(scope["key"])
        yield scope
