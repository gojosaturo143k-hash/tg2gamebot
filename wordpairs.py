"""
Word pair bank for Secret Word Odd One Out.

Each pair holds a COMMON word (most players get this) and an ODD word
(one player gets this). Pairs are deliberately related so the Odd Player
has a fair chance to bluff.

Structure: (common, odd, category, difficulty)
"""

import random

PAIRS = [
    # ── FOOD ──
    ("APPLE", "ORANGE", "Food", "Easy", "🍎", "🍊"),
    ("PIZZA", "BURGER", "Food", "Easy", "🍕", "🍔"),
    ("COFFEE", "TEA", "Food", "Easy", "☕", "🍵"),
    ("BREAD", "CAKE", "Food", "Easy", "🍞", "🍰"),
    ("RICE", "PASTA", "Food", "Medium", "🍚", "🍝"),
    ("ICE CREAM", "YOGURT", "Food", "Medium", "🍦", "🥛"),
    ("CHOCOLATE", "CANDY", "Food", "Medium", "🍫", "🍬"),
    ("SOUP", "STEW", "Food", "Hard", "🍲", "🥘"),
    ("BANANA", "MANGO", "Food", "Easy", "🍌", "🥭"),
    ("CHEESE", "BUTTER", "Food", "Medium", "🧀", "🧈"),
    ("SANDWICH", "WRAP", "Food", "Hard", "🥪", "🌯"),
    ("HONEY", "SYRUP", "Food", "Hard", "🍯", "🥞"),
    ("SALAD", "SOUP", "Food", "Medium", "🥗", "🍲"),
    ("EGG", "MILK", "Food", "Easy", "🥚", "🥛"),
    ("NOODLES", "DUMPLING", "Food", "Medium", "🍜", "🥟"),
    ("POPCORN", "CHIPS", "Food", "Easy", "🍿", "🥔"),
    ("STRAWBERRY", "CHERRY", "Food", "Medium", "🍓", "🍒"),
    ("WATERMELON", "PINEAPPLE", "Food", "Easy", "🍉", "🍍"),

    # ── ANIMALS ──
    ("CAT", "DOG", "Animals", "Easy", "🐱", "🐶"),
    ("LION", "TIGER", "Animals", "Medium", "🦁", "🐯"),
    ("ELEPHANT", "RHINO", "Animals", "Medium", "🐘", "🦏"),
    ("EAGLE", "HAWK", "Animals", "Hard", "🦅", "🦉"),
    ("SHARK", "WHALE", "Animals", "Easy", "🦈", "🐋"),
    ("RABBIT", "HAMSTER", "Animals", "Medium", "🐰", "🐹"),
    ("HORSE", "DONKEY", "Animals", "Medium", "🐴", "🫏"),
    ("SNAKE", "LIZARD", "Animals", "Medium", "🐍", "🦎"),
    ("BEE", "BUTTERFLY", "Animals", "Easy", "🐝", "🦋"),
    ("PENGUIN", "SEAL", "Animals", "Medium", "🐧", "🦭"),
    ("MONKEY", "GORILLA", "Animals", "Medium", "🐵", "🦍"),
    ("COW", "GOAT", "Animals", "Easy", "🐄", "🐐"),
    ("FROG", "TURTLE", "Animals", "Easy", "🐸", "🐢"),
    ("WOLF", "FOX", "Animals", "Hard", "🐺", "🦊"),
    ("PARROT", "PIGEON", "Animals", "Medium", "🦜", "🕊️"),
    ("CROCODILE", "HIPPO", "Animals", "Medium", "🐊", "🦛"),

    # ── SPORTS ──
    ("FOOTBALL", "BASKETBALL", "Sports", "Easy", "⚽", "🏀"),
    ("CRICKET", "BASEBALL", "Sports", "Medium", "🏏", "⚾"),
    ("TENNIS", "BADMINTON", "Sports", "Medium", "🎾", "🏸"),
    ("SWIMMING", "DIVING", "Sports", "Medium", "🏊", "🤿"),
    ("BOXING", "WRESTLING", "Sports", "Medium", "🥊", "🤼"),
    ("SKATING", "SKIING", "Sports", "Hard", "⛸️", "⛷️"),
    ("CHESS", "CHECKERS", "Sports", "Hard", "♟️", "🔴"),
    ("GOLF", "HOCKEY", "Sports", "Easy", "⛳", "🏒"),
    ("RUNNING", "CYCLING", "Sports", "Easy", "🏃", "🚴"),
    ("VOLLEYBALL", "HANDBALL", "Sports", "Hard", "🏐", "🤾"),
    ("ARCHERY", "SHOOTING", "Sports", "Hard", "🏹", "🎯"),
    ("SURFING", "SAILING", "Sports", "Medium", "🏄", "⛵"),

    # ── TECHNOLOGY ──
    ("PHONE", "TABLET", "Technology", "Easy", "📱", "💻"),
    ("LAPTOP", "DESKTOP", "Technology", "Medium", "💻", "🖥️"),
    ("CAMERA", "BINOCULARS", "Technology", "Medium", "📷", "🔭"),
    ("HEADPHONES", "SPEAKER", "Technology", "Easy", "🎧", "🔊"),
    ("KEYBOARD", "MOUSE", "Technology", "Easy", "⌨️", "🖱️"),
    ("BATTERY", "CHARGER", "Technology", "Medium", "🔋", "🔌"),
    ("ROBOT", "DRONE", "Technology", "Medium", "🤖", "🛸"),
    ("WEBSITE", "APP", "Technology", "Hard", "🌐", "📲"),
    ("PRINTER", "SCANNER", "Technology", "Hard", "🖨️", "📠"),
    ("EMAIL", "MESSAGE", "Technology", "Medium", "📧", "💬"),
    ("PASSWORD", "USERNAME", "Technology", "Hard", "🔑", "👤"),
    ("WIFI", "BLUETOOTH", "Technology", "Medium", "📶", "🔵"),

    # ── SCHOOL ──
    ("PENCIL", "PEN", "School", "Easy", "✏️", "🖊️"),
    ("BOOK", "NOTEBOOK", "School", "Easy", "📖", "📓"),
    ("TEACHER", "STUDENT", "School", "Easy", "👨‍🏫", "🧑‍🎓"),
    ("EXAM", "HOMEWORK", "School", "Medium", "📝", "📚"),
    ("RULER", "ERASER", "School", "Easy", "📏", "🧽"),
    ("MATH", "SCIENCE", "School", "Medium", "➗", "🔬"),
    ("LIBRARY", "CLASSROOM", "School", "Medium", "📚", "🏫"),
    ("BACKPACK", "LUNCHBOX", "School", "Easy", "🎒", "🍱"),
    ("HISTORY", "GEOGRAPHY", "School", "Hard", "📜", "🗺️"),
    ("DIPLOMA", "CERTIFICATE", "School", "Hard", "🎓", "📃"),

    # ── PLACES ──
    ("BEACH", "DESERT", "Places", "Easy", "🏖️", "🏜️"),
    ("MOUNTAIN", "HILL", "Places", "Hard", "⛰️", "🏔️"),
    ("HOSPITAL", "CLINIC", "Places", "Medium", "🏥", "💊"),
    ("HOTEL", "RESORT", "Places", "Medium", "🏨", "🏝️"),
    ("MARKET", "MALL", "Places", "Medium", "🏪", "🛍️"),
    ("PARK", "GARDEN", "Places", "Medium", "🏞️", "🌷"),
    ("AIRPORT", "STATION", "Places", "Medium", "✈️", "🚉"),
    ("CASTLE", "PALACE", "Places", "Hard", "🏰", "🕌"),
    ("FARM", "RANCH", "Places", "Hard", "🚜", "🐎"),
    ("CITY", "VILLAGE", "Places", "Easy", "🏙️", "🏡"),
    ("MUSEUM", "GALLERY", "Places", "Hard", "🏛️", "🖼️"),
    ("BRIDGE", "TUNNEL", "Places", "Easy", "🌉", "🚇"),

    # ── OBJECTS ──
    ("CHAIR", "TABLE", "Objects", "Easy", "🪑", "🪵"),
    ("UMBRELLA", "RAINCOAT", "Objects", "Medium", "☂️", "🧥"),
    ("CLOCK", "WATCH", "Objects", "Medium", "🕐", "⌚"),
    ("MIRROR", "WINDOW", "Objects", "Medium", "🪞", "🪟"),
    ("KEY", "LOCK", "Objects", "Easy", "🔑", "🔒"),
    ("CANDLE", "LAMP", "Objects", "Easy", "🕯️", "💡"),
    ("BOTTLE", "CUP", "Objects", "Easy", "🍾", "🥤"),
    ("BROOM", "MOP", "Objects", "Medium", "🧹", "🧽"),
    ("SCISSORS", "KNIFE", "Objects", "Medium", "✂️", "🔪"),
    ("PILLOW", "BLANKET", "Objects", "Easy", "🛏️", "🧸"),
    ("BASKET", "BOX", "Objects", "Hard", "🧺", "📦"),
    ("WALLET", "PURSE", "Objects", "Hard", "👛", "👝"),
    ("LADDER", "STAIRS", "Objects", "Medium", "🪜", "🪞"),
    ("HAMMER", "SCREWDRIVER", "Objects", "Medium", "🔨", "🪛"),

    # ── GAMES ──
    ("PUZZLE", "RIDDLE", "Games", "Hard", "🧩", "❓"),
    ("CARDS", "DICE", "Games", "Easy", "🃏", "🎲"),
    ("VIDEO GAME", "BOARD GAME", "Games", "Medium", "🎮", "🎲"),
    ("HIDE AND SEEK", "TAG", "Games", "Medium", "🙈", "🏃"),
    ("LEGO", "BLOCKS", "Games", "Hard", "🧱", "🟦"),
    ("JOYSTICK", "CONTROLLER", "Games", "Hard", "🕹️", "🎮"),

    # ── MOVIES ──
    ("CINEMA", "THEATER", "Movies", "Medium", "🎬", "🎭"),
    ("ACTOR", "DIRECTOR", "Movies", "Medium", "🎭", "🎬"),
    ("COMEDY", "DRAMA", "Movies", "Medium", "😂", "😢"),
    ("HORROR", "THRILLER", "Movies", "Hard", "👻", "🔪"),
    ("POPCORN", "TICKET", "Movies", "Easy", "🍿", "🎟️"),
    ("SUPERHERO", "VILLAIN", "Movies", "Easy", "🦸", "🦹"),

    # ── CARTOONS ──
    ("CARTOON", "ANIME", "Cartoons", "Medium", "📺", "🎌"),
    ("MICKEY MOUSE", "DONALD DUCK", "Cartoons", "Easy", "🐭", "🦆"),
    ("TOM", "JERRY", "Cartoons", "Easy", "🐱", "🐭"),
    ("WIZARD", "FAIRY", "Cartoons", "Medium", "🧙", "🧚"),
    ("DRAGON", "DINOSAUR", "Cartoons", "Medium", "🐉", "🦖"),
    ("PIRATE", "NINJA", "Cartoons", "Easy", "🏴‍☠️", "🥷"),

    # ── NATURE ──
    ("SUMMER", "WINTER", "Nature", "Easy", "☀️", "❄️"),
    ("OCEAN", "RIVER", "Nature", "Easy", "🌊", "🏞️"),
    ("RAIN", "SNOW", "Nature", "Easy", "🌧️", "🌨️"),
    ("TREE", "FLOWER", "Nature", "Easy", "🌳", "🌸"),
    ("SUN", "MOON", "Nature", "Easy", "☀️", "🌙"),
    ("FOREST", "JUNGLE", "Nature", "Hard", "🌲", "🌴"),
    ("STORM", "TORNADO", "Nature", "Medium", "⛈️", "🌪️"),
    ("VOLCANO", "EARTHQUAKE", "Nature", "Medium", "🌋", "🏚️"),
    ("CLOUD", "FOG", "Nature", "Medium", "☁️", "🌫️"),
    ("LAKE", "POND", "Nature", "Hard", "🏞️", "💧"),
    ("STAR", "PLANET", "Nature", "Easy", "⭐", "🪐"),
    ("SPRING", "AUTUMN", "Nature", "Medium", "🌸", "🍂"),

    # ── DAILY LIFE ──
    ("BREAKFAST", "DINNER", "Daily Life", "Easy", "🍳", "🍽️"),
    ("SHOWER", "BATH", "Daily Life", "Medium", "🚿", "🛁"),
    ("SLEEP", "NAP", "Daily Life", "Hard", "😴", "💤"),
    ("SHOPPING", "COOKING", "Daily Life", "Easy", "🛒", "👨‍🍳"),
    ("BIRTHDAY", "WEDDING", "Daily Life", "Easy", "🎂", "💒"),
    ("MONEY", "CREDIT CARD", "Daily Life", "Medium", "💵", "💳"),
    ("SOAP", "SHAMPOO", "Daily Life", "Medium", "🧼", "🧴"),
    ("TOOTHBRUSH", "COMB", "Daily Life", "Medium", "🪥", "🪮"),
    ("HOLIDAY", "WEEKEND", "Daily Life", "Hard", "🏖️", "📅"),
    ("MORNING", "EVENING", "Daily Life", "Easy", "🌅", "🌆"),

    # ── TRANSPORT ──
    ("BUS", "TRAIN", "Transport", "Easy", "🚌", "🚆"),
    ("CAR", "TRUCK", "Transport", "Easy", "🚗", "🚚"),
    ("BICYCLE", "MOTORCYCLE", "Transport", "Easy", "🚲", "🏍️"),
    ("AIRPLANE", "HELICOPTER", "Transport", "Easy", "✈️", "🚁"),
    ("BOAT", "SHIP", "Transport", "Hard", "🛶", "🚢"),
    ("TAXI", "AMBULANCE", "Transport", "Medium", "🚕", "🚑"),
    ("SUBWAY", "TRAM", "Transport", "Hard", "🚇", "🚊"),
    ("ROCKET", "SATELLITE", "Transport", "Medium", "🚀", "🛰️"),
    ("SCOOTER", "SKATEBOARD", "Transport", "Medium", "🛴", "🛹"),

    # ── PROFESSIONS ──
    ("DOCTOR", "NURSE", "Professions", "Easy", "👨‍⚕️", "👩‍⚕️"),
    ("POLICE", "SOLDIER", "Professions", "Medium", "👮", "🪖"),
    ("CHEF", "BAKER", "Professions", "Medium", "👨‍🍳", "🥖"),
    ("PILOT", "DRIVER", "Professions", "Easy", "👨‍✈️", "🚗"),
    ("FARMER", "GARDENER", "Professions", "Hard", "👨‍🌾", "🌻"),
    ("ARTIST", "MUSICIAN", "Professions", "Easy", "🎨", "🎵"),
    ("ENGINEER", "ARCHITECT", "Professions", "Hard", "⚙️", "📐"),
    ("LAWYER", "JUDGE", "Professions", "Medium", "⚖️", "👨‍⚖️"),
    ("FIREFIGHTER", "LIFEGUARD", "Professions", "Medium", "🚒", "🏊"),
    ("SCIENTIST", "INVENTOR", "Professions", "Hard", "🔬", "💡"),
    ("WRITER", "JOURNALIST", "Professions", "Hard", "✍️", "📰"),
    ("BARBER", "TAILOR", "Professions", "Medium", "💈", "🧵"),

    # ── MUSIC / INSTRUMENTS ──
    ("GUITAR", "PIANO", "Objects", "Easy", "🎸", "🎹"),
    ("DRUMS", "VIOLIN", "Objects", "Easy", "🥁", "🎻"),
    ("FLUTE", "TRUMPET", "Objects", "Medium", "🪈", "🎺"),
    ("SONG", "POEM", "Objects", "Hard", "🎵", "📜"),

    # ── CLOTHING ──
    ("SHIRT", "JACKET", "Objects", "Easy", "👕", "🧥"),
    ("SHOES", "SANDALS", "Objects", "Medium", "👟", "🩴"),
    ("HAT", "CAP", "Objects", "Hard", "🎩", "🧢"),
    ("GLOVES", "SOCKS", "Objects", "Medium", "🧤", "🧦"),
    ("DRESS", "SKIRT", "Objects", "Medium", "👗", "👚"),
    ("GLASSES", "SUNGLASSES", "Objects", "Hard", "👓", "🕶️"),
]


def total_pairs():
    return len(PAIRS)


def get_pair(index):
    """Return a pair dict by index."""
    if index < 0 or index >= len(PAIRS):
        index = 0
    common, odd, category, difficulty, c_emoji, o_emoji = PAIRS[index]
    return {
        "index": index,
        "common": common,
        "odd": odd,
        "category": category,
        "difficulty": difficulty,
        "common_emoji": c_emoji,
        "odd_emoji": o_emoji,
    }


def pick_pair(exclude=None):
    """
    Pick a random pair, avoiding indices in `exclude`.
    Falls back to the full pool once everything has been used.
    """
    exclude = set(exclude or [])
    available = [i for i in range(len(PAIRS)) if i not in exclude]
    if not available:
        available = list(range(len(PAIRS)))

    index = random.choice(available)

    # 50/50 swap so the "common" side isn't always the same word
    pair = get_pair(index)
    if random.random() < 0.5:
        pair = {
            "index": index,
            "common": pair["odd"],
            "odd": pair["common"],
            "category": pair["category"],
            "difficulty": pair["difficulty"],
            "common_emoji": pair["odd_emoji"],
            "odd_emoji": pair["common_emoji"],
        }
    return pair
