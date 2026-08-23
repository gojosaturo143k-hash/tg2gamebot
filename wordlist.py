"""
English word dictionary for word-based games.

The bundled list below is a baseline of common English words.
Authoritative validation is done online through dictionary APIs.

Validation pipeline for Word Chain submissions:
  1. used-word check (handled in wordchain.py)
  2. global validation cache
  3. primary dictionary API (FreeDictionaryAPI)
  4. fallback dictionary API (DictionaryAPI.dev)
  5. cache definitive results (never cache temporary failures)

A word counts as VALID only when the API response contains a genuine
dictionary entry for the exact requested word, including at least one
real definition. An HTTP 200 or an arbitrary JSON payload is NOT enough.
"""

import asyncio
from urllib.parse import quote

import aiohttp

# ── Bundled common English words (guaranteed baseline) ──
_BUNDLED = """
able about above absent absorb abuse accept access accident account accuse ache achieve acid acquire across
act action active activity actor actual adapt add addition address adjust admire admit adopt adult advance
advantage adventure advice advise affair affect afford afraid after afternoon again against age agency agent
aggressive ago agree agreement ahead aid aim air aircraft airline airport alarm album alcohol alert alien
alive all allow almost alone along aloud already also alter although always amaze amazing ambition among
amount ample amuse analysis ancient anger angle angry animal ankle announce annoy annual another answer ant
anxiety anxious any anybody anyone anything anywhere apart apartment apology appeal appear apple apply
appoint approach approve april architect area argue argument arise arm army around arrange arrest arrival
arrive arrow art article artist ash aside ask asleep aspect assist assume assure athlete atlas atmosphere
atom attach attack attempt attend attention attitude attract auction audience august aunt author authority
auto autumn available avenue average avoid awake award aware away awesome awful axe
baby back background backward bacon bad badge bag bake balance balcony ball balloon banana band bank bar
barber bare bargain bark barn barrel base baseball basic basin basket bat bath bathroom battery battle bay
beach bead beam bean bear beard beast beat beautiful beauty because become bed bedroom bee beef beer before
beg begin beginner behave behind being belief believe bell belong below belt bench bend beneath benefit
berry beside best bet better between beyond bicycle big bike bill bin bind bird birth birthday biscuit bit
bite bitter black blade blame blank blanket blast blaze bleed blend bless blind blink block blood bloom blow
blue board boat body boil bold bolt bomb bond bone bonus book boot border bore born borrow boss both bother
bottle bottom bounce bound bow bowl box boy brain brake branch brand brave bread break breakfast breath
breathe breed breeze brick bride bridge brief bright brilliant bring broad broken bronze brook broom brother
brown brush bubble bucket buddy budget buffalo bug build building bulb bull bullet bunch bundle burden burn
burst bury bus bush business busy but butter button buy buzz
cabin cabinet cable cactus cafe cage cake calculate calendar call calm camel camera camp campaign canal
cancel candle candy cannon canoe canvas cap capable capacity cape capital captain capture car carbon card
care career careful cargo carpet carriage carrot carry cart carve case cash cast castle cat catch category
cattle cause caution cave ceiling celebrate cell cellar cement cent center central century ceremony certain
chain chair chalk challenge chamber champion chance change channel chaos chapter character charge charity
charm chart chase cheap cheat check cheek cheer cheese chef chemical cherry chess chest chew chicken chief
child childhood chill chimney chin chip chocolate choice choose chop chorus church cinema circle circuit
circus citizen city civil claim clap class classic classroom clay clean clear clerk clever click client
cliff climate climb clinic clip clock close cloth clothes cloud club clue coach coal coast coat code coffee
coin cold collar collect college colony color column comb combine come comedy comfort comic command comment
commerce commit common communicate community compact company compare compass compete complete complex
computer concept concern concert conclude concrete condition conduct confess confirm conflict confuse
congress connect conquer conscience consent consider consist constant construct consult consume contact
contain content contest context continue contract contrast contribute control convince cook cool cooperate
copper copy coral cord core corn corner correct cost cottage cotton couch cough council count counter country
county couple courage course court cousin cover cow crack craft crash crawl crazy cream create creature
credit creek crew cricket crime crisis crisp critic crop cross crowd crown crucial cruel cruise crush cry
crystal cube culture cup cupboard cure curious curl currency current curtain curve cushion custom customer
cut cute cycle
dad daily dairy damage damp dance danger dare dark data date daughter dawn day dead deaf deal dear death
debate debt decade decay december decide deck declare decline decorate decrease deep deer defeat defend
define degree delay delicate delight deliver demand democracy demonstrate denial dense dental deny depart
depend deposit depth derive describe desert deserve design desire desk desperate despite dessert destroy
detail detect determine develop device devote diagram dial diamond diary dictionary die diet differ different
difficult dig digital dignity dinner dinosaur direct direction dirt dirty disagree disappear disaster
discipline discount discover discuss disease disguise dish dislike dismiss display distance distant distinct
distribute district disturb dive divide divine division divorce doctor document dog doll dollar dolphin
domain domestic dominate donate donkey door dose dot double doubt dough down downtown dozen draft drag dragon
drain drama draw drawer dream dress drift drill drink drive drop drown drug drum dry duck due dull dump
during dust duty dwell dye dynamic
each eager eagle ear early earn earth ease east easy eat echo ecology economy edge edit educate effect effort
egg eight either elbow elder elect electric electron elegant element elephant elevator else elsewhere embrace
emerge emergency emotion emperor empire employ empty enable enclose encounter encourage end endless endure
enemy energy engage engine engineer enhance enjoy enormous enough enrich ensure enter entertain enthusiasm
entire entrance entry envelope environment envy equal equip equipment era error escape especially essay
essential establish estate estimate eternal evaluate eve even evening event ever every everybody everyone
everything everywhere evidence evil evolve exact exam examine example exceed excellent except exchange excite
exclude excuse execute exercise exhaust exhibit exist exit expand expect expense experience experiment expert
explain explore export expose express extend external extra extreme eye
fabric face fact factor factory fade fail failure faint fair faith fall false fame familiar family famous fan
fancy fantastic fantasy far fare farm farmer fashion fast fasten fat fatal fate father fatigue fault favor
favorite fear feast feather feature february federal fee feed feel fellow female fence festival fetch fever
few fiber fiction field fierce fifteen fifth fifty fight figure file fill film filter final finance find fine
finger finish fire firm first fish fist fit five fix flag flame flash flat flavor flee fleet flesh flexible
flight float flood floor flour flow flower fluid flute fly foam focus fog fold folk follow fond food fool
foot football force forecast forehead foreign forest forever forget forgive fork form formal format former
fortune forty forward fossil foster found foundation fountain four fourteen fox fragile frame frank free
freedom freeze frequent fresh friday friend friendly frighten frog front frost frown fruit fry fuel full fun
function fund fundamental funeral funny fur furniture further future
gain galaxy gallery gallon game gang gap garage garbage garden garlic garment gas gasp gate gather gauge gaze
gear gender gene general generate generation generous genius gentle gentleman genuine geography germ gesture
ghost giant gift gigantic giggle ginger giraffe girl give glad glance glass glide glimpse global globe gloom
glory glove glow glue goal goat gold golden golf good goodbye goose gorgeous govern government gown grab
grace grade gradual graduate grain grand grandfather grandmother grant grape graph grasp grass grateful grave
gravity gray great green greet grid grief grill grin grind grip grocery ground group grow growth guarantee
guard guess guest guide guilt guilty guitar gulf gun guy gym
habit hair half hall halt hammer hand handle handsome hang happen happy harbor hard hardly harm harmony harsh
harvest hat hate haul have hawk hay hazard head headache heal health healthy hear heart heat heaven heavy
hedge heel height helicopter hello helmet help helpful hen herb here heritage hero hesitate hidden hide high
highlight highway hill hint hip hire historic history hit hobby hockey hold hole holiday hollow holy home
homework honest honey honor hook hope horizon horn horror horse hospital host hot hotel hour house household
housing hover however hug huge human humble humid humor hundred hunger hungry hunt hurricane hurry hurt
husband hut hydrogen
ice icon idea ideal identify identity idle ignore ill illegal illness illustrate image imagine immediate
immense immune impact implement imply import important impose impress improve impulse inch incident include
income increase indeed independent index indicate indoor industry infant infect inform ingredient inherit
initial inject injure injury ink inner innocent input inquire insect insert inside insight insist inspect
inspire install instance instant instead institute instruct instrument insult insurance intake integrate
intend intense interest interior internal international internet interpret interrupt interval interview
introduce invade invent invest investigate invite involve iron island isolate issue item ivory
jacket jail jam january jar jaw jazz jealous jeans jelly jet jewel job join joint joke journal journey joy
judge juice july jump june jungle junior jury just justice justify
keen keep kettle key keyboard kick kid kidney kill kilogram kind king kingdom kiss kit kitchen kite kitten
knee kneel knife knight knit knock knot know knowledge
label labor laboratory lack ladder lady lake lamb lamp land landscape lane language lantern lap large laser
last late later laugh launch laundry law lawn lawyer lay layer lazy lead leader leaf league lean leap learn
lease least leather leave lecture left leg legal legend legislation leisure lemon lend length lens leopard
less lesson letter level liberal liberty library license lid lie life lift light lightning like likely limb
limit line link lion lip liquid list listen literature little live lively liver living lizard load loan lobby
local locate lock lodge log logic lonely long look loop loose lord lose loss lost lot loud love lovely low
loyal luck lucky luggage lump lunch lung luxury
machine mad magazine magic magnet mail main maintain major make male mall mammal man manage manager mango
manner mansion manual manufacture many map marble march margin marine mark market marriage marry marvel mask
mass master mat match mate material matter mature maximum maybe mayor meadow meal mean meaning measure meat
mechanic medal media medical medicine medium meet melody melon melt member memory mental mention menu mercy
mere merge merit merry mess message metal meter method middle midnight might mild mile military milk mill
million mind mine mineral minimum minister minor minute miracle mirror miss missile mission mist mistake mix
mixture mobile mode model moderate modern modest modify moist moment monday money monitor monkey month
monument mood moon moral morning mortgage mother motion motivate motor mount mountain mouse mouth move
movement movie much mud multiple murder muscle museum mushroom music musical mustard mutual mystery myth
nail naked name narrow nation national native natural nature naval navy near nearly neat necessary neck need
needle negative neglect negotiate neighbor nephew nerve nervous nest net network neutral never nevertheless
new news newspaper next nice niece night nine nineteen ninety noble nobody nod noise none nonsense noon
normal north nose note nothing notice notion noun november now nowhere nuclear number numerous nurse nut
nutrition
oak obey object obligation observe obtain obvious occasion occupy occur ocean october odd odor offer office
officer official often oil old olive omit once onion online only onto open opera operate opinion opponent
opportunity oppose opposite option orange orbit orchard order ordinary organ organic organize origin original
other otherwise ought outcome outdoor outer outfit outline output outside oval oven over overall overcome
overlook overseas owe owl own owner oxygen oyster
pace pack package page pain paint pair palace pale palm pan panel panic paper parade paragraph parallel
parent park parliament part participate particular partner party pass passage passenger passion passport past
pasta paste path patience patient pattern pause pave pay payment peace peach peak peanut pear pearl peasant
peculiar pen penalty pencil penny people pepper perceive percent perfect perform perhaps period permanent
permit person personal perspective persuade pet phase phone photo phrase physical piano pick picture pie
piece pig pigeon pile pill pillow pilot pin pine pink pint pioneer pipe pirate pit pitch pity pizza place
plain plan plane planet plant plastic plate platform play player pleasant please pleasure plenty plot plug
plus pocket poem poet poetry point poison pole police policy polish polite political pollution pond pool poor
pop popular population porch port portion portrait position positive possess possible post postpone pot
potato potential pound pour poverty powder power powerful practical practice praise pray precious precise
predict prefer pregnant premium prepare presence present preserve president press pressure pretend pretty
prevent previous price pride priest primary prime prince princess principal principle print prior prison
private prize probable problem procedure proceed process produce product profession professor profile profit
program progress project promise promote prompt proof proper property proportion proposal propose prospect
protect protein protest proud prove provide province provoke public publish pull pulse pump punch punish
pupil puppy purchase pure purple purpose purse pursue push put puzzle pyramid
qualify quality quantity quarrel quarter queen query quest question queue quick quiet quilt quit quite quiz
quota quote
rabbit race rack radar radio radius rag rage raid rail railway rain rainbow raise rally ranch random range
rank rapid rare rat rate rather ratio raw ray reach react read ready real reality realize really rear reason
rebel recall receipt receive recent recipe recognize recommend record recover recruit reduce refer reflect
reform refuge refuse regard region register regret regular reject relate relation relax release relevant
relief religion rely remain remark remedy remember remind remote remove rent repair repeat replace reply
report represent republic reputation request require rescue research resemble reserve resident resist resolve
resort resource respect respond response responsible rest restaurant restore result retain retire retreat
return reveal revenue reverse review revise revolution reward rhythm rib ribbon rice rich rid ride ridge rifle
right rigid ring riot rip ripe rise risk ritual rival river road roar roast rob robot rock rocket rod role
roll roof room root rope rose rough round route routine row royal rub rubber rubbish rude rug ruin rule ruler
rumor run runner rural rush rust
sacred sad saddle safe safety sail sailor saint salad salary sale salmon salt same sample sand sandwich
satellite satisfy saturday sauce sausage save saw say scale scan scandal scar scarce scare scarf scatter
scene schedule scheme scholar school science scientist scissors scope score scout scramble scrap scratch
scream screen screw script sculpture sea seal search season seat second secret secretary section sector
secure seed seek seem segment seize seldom select self sell senate send senior sense sensitive sentence
separate september sequence series serious servant serve service session settle seven seventeen seventy
several severe sew shade shadow shake shallow shame shape share shark sharp shave shed sheep sheet shelf
shell shelter shield shift shine ship shirt shock shoe shoot shop shore short shot shoulder shout show shower
shrimp shrink shut shy sick side sight sign signal signature significant silence silent silk silly silver
similar simple simply since sincere sing singer single sink sister sit site situation six sixteen sixty size
skate sketch ski skill skin skip skirt skull sky slam slave sleep sleeve slice slide slight slim slip slope
slot slow small smart smash smell smile smoke smooth snack snake snap sneak snow soap soccer social society
sock soft software soil solar soldier sole solid solution solve somebody somehow someone something sometime
somewhat somewhere son song soon sore sorrow sorry sort soul sound soup source south space spare spark speak
special species specific speech speed spell spend sphere spice spider spill spin spirit spit split spoil
sponsor spoon sport spot spray spread spring spy square squeeze stable stadium staff stage stair stake stamp
stand standard star stare start state statement station statue status stay steady steak steal steam steel
steep steer stem step stick stiff still sting stir stock stomach stone stool stop storage store storm story
stove straight strain strange stranger strap strategy straw stream street strength stress stretch strict
strike string strip stripe stroke strong structure struggle student studio study stuff stupid style subject
submit substance subtle succeed success sudden suffer sugar suggest suit suitable summer summit sun sunday
sunny sunset super superb supermarket supply support suppose sure surface surgery surprise surround survey
survive suspect suspend sustain swallow swamp swan swap swear sweat sweater sweep sweet swell swift swim
swing switch sword symbol sympathy symptom system
table tablet tackle tag tail tailor take tale talent talk tall tank tap tape target task taste tax taxi tea
teach teacher team tear tease technical technique technology teenager telephone telescope television tell
temperature temple temporary tempt ten tenant tend tender tennis tension tent term terrible territory terror
test text thank theater theme theory therapy therefore thick thief thin thing think third thirst thirteen
thirty thorough though thought thousand thread threat three throat throne through throw thumb thunder
thursday ticket tide tidy tie tiger tight tile timber time tin tiny tip tire tired tissue title toast tobacco
today toe together toilet token tolerate tomato tomorrow ton tone tongue tonight tool tooth top topic torch
torture toss total touch tough tour tourist tournament toward towel tower town toy trace track trade tradition
traffic tragedy trail train trait transfer transform transit translate transport trap trash travel tray
treasure treat treaty tree tremble trend trial triangle tribe trick trigger trim trip triumph troop tropical
trouble truck true trust truth try tube tuesday tune tunnel turkey turn turtle twelve twenty twice twin twist
type typical
ugly ultimate umbrella unable uncle under undergo underline understand undertake underwater undo unemployed
unexpected unfair unfold unhappy uniform union unique unit unite universe university unknown unless unlike
unlock unusual update upgrade uphold upon upper upset upstairs urban urge urgent use useful useless user usual
utility utter
vacation vacuum vague valid valley valuable value van vanish variety various vary vast vault vegetable
vehicle veil vein velvet vendor venture venue verb verdict verify verse version vertical vessel veteran
vibrate victim victory video view village vinegar violence violet violin virtue virus visible vision visit
visitor visual vital vivid vocabulary voice volcano volume volunteer vote voyage
wage wagon waist wait wake walk wall wallet wander want war warm warn warrant wash waste watch water wave wax
weak wealth weapon wear weather weave web wedding wednesday weed week weekend weekly weigh weight weird
welcome welfare west western wet whale wheat wheel whip whisper whistle white whole wide widow width wife wild
willing win wind window wine wing wink winner winter wipe wire wisdom wise wish wit witch withdraw within
without witness wolf woman wonder wonderful wood wool word work worker world worm worry worse worship worst
worth wound wrap wreck wrist write writer wrong
xenon xerox xylophone
yard yarn yawn year yell yellow yesterday yield yoga yogurt young youth
zebra zero zone zoo zoom
"""

# Curated common words form a negative-proof cache plus letter stats.
WORDS = set()
_LETTER_COUNTS = {}


def _load():
    """Build the bundled word set once at import time."""
    global WORDS, _LETTER_COUNTS

    words = set()
    for w in _BUNDLED.split():
        w = w.strip().lower()
        if len(w) >= 2 and w.isalpha():
            words.add(w)

    WORDS = words

    counts = {}
    for w in words:
        c = w[0]
        counts[c] = counts.get(c, 0) + 1
    _LETTER_COUNTS = counts


_load()


def letter_word_count(letter):
    """How many dictionary words start with this letter."""
    return _LETTER_COUNTS.get(letter.lower(), 0)


def resolve_next_letter(word, minimum=25):
    """
    Pick the required starting letter for the next turn.

    Normally this is the last letter of `word`. But letters like
    'x' or 'q' have almost no words, which would softlock the game.
    In that case we walk backwards to find a usable letter.
    """
    w = (word or "").strip().lower()
    if not w:
        return "a"

    for ch in reversed(w):
        if ch.isalpha() and letter_word_count(ch) >= minimum:
            return ch

    return w[-1] if w[-1].isalpha() else "a"


def random_start_letter():
    """Pick a friendly random letter to open the game with."""
    import random
    pool = [c for c in "abcdefghijklmnoprstuvw" if letter_word_count(c) >= 100]
    return random.choice(pool) if pool else "a"


def dictionary_size():
    return len(WORDS)


# ═══════════════════════════════════════════════
# API-BASED WORD VALIDATION (primary source of truth)
#
# Flow per word:
#   used-word check (in game module) ->
#   cache -> primary API -> fallback API -> cache result
#
# Network failures are NEVER cached; only definitive
# answers (valid / invalid) are stored.
# ═══════════════════════════════════════════════

PRIMARY_API_URL = "https://freedictionaryapi.com/api/v1/entries/en/{}"
FALLBACK_API_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/{}"

API_TIMEOUT_SECONDS = 10
MAX_WORD_LENGTH = 50
MIN_WORD_LENGTH_FOR_API = 2

# HTTP codes where we fall back to the secondary API
_FALLBACK_STATUSES = {400, 429, 500, 502, 503, 504}


class WordStatus:
    """Three-way result so an API failure is distinct from a bad word."""
    VALID = "valid"
    INVALID = "invalid"
    ERROR = "error"  # verification unavailable, player may retry


class ValidationResult:
    """Word validation outcome."""
    __slots__ = ("status", "word")

    def __init__(self, status, word):
        self.status = status
        self.word = word

    def __bool__(self):
        return self.status == WordStatus.VALID


# Global validation cache — shared across ALL groups.
# The local bundled dictionary acts as a pre-seeded positive cache,
# so common words never need a network request.
_cache = {w: True for w in WORDS}

# In-flight lookups, so multiple groups validating the same word share
# a single API request instead of racing.
_pending = {}


def normalize_word(raw):
    """
    Normalize user input for validation.

    Returns the cleaned lowercase word, or None when the input is
    unusable (empty, too short/long, contains digits or symbols).
    """
    if raw is None:
        return None

    w = str(raw).strip().lower()

    if not w:
        return None
    if len(w) < MIN_WORD_LENGTH_FOR_API or len(w) > MAX_WORD_LENGTH:
        return None
    # Reject numbers, symbols and mixed junk like "random123" / "!!!"
    if not w.isalpha():
        return None

    return w


_NON_WORD_PAYLOAD_TERMS = (
    "may refer to", "disambiguation", "wikipedia",
    "wikipedia page", "no definitions found",
)


def _looks_like_non_word_payload(text):
    """Detect Wikipedia/disambiguation/other junk payloads."""
    lowered = (text or "").lower()
    return any(term in lowered for term in _NON_WORD_PAYLOAD_TERMS)


def _matches_exact_word(value, word):
    """An API word field must match the exact normalized submission."""
    try:
        candidate = str(value or "").strip().lower()
    except Exception:
        return False
    return candidate == word


def _is_deep_primary_valid(data, word, depth=0):
    """
    Strict recursive validation for FreeDictionaryAPI-style payloads.

    A valid dictionary entry for the exact word must contain non-empty
    dictionary data and at least one sense with a real definition.
    """
    if depth > 50:
        return False

    if isinstance(data, list):
        if not data:
            return False
        return any(_is_deep_primary_valid(item, word, depth + 1) for item in data)

    if not isinstance(data, dict):
        return False

    lowered = {str(k).lower(): v for k, v in data.items()}

    # The response must be about the exact requested word when a word field exists.
    if not _matches_exact_word(
        lowered.get("word") or lowered.get("entry") or lowered.get("name"),
        word,
    ):
        return False

    # Require non-empty entries.
    entries = lowered.get("entries") or lowered.get("meanings")
    if not isinstance(entries, list) or not entries:
        return False

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_lowered = {str(k).lower(): v for k, v in entry.items()}

        # Either a definition directly on the entry, or senses with definitions.
        direct_def = str(entry_lowered.get("definition", "")).strip()
        if direct_def and not _looks_like_non_word_payload(direct_def):
            return True

        senses = entry_lowered.get("senses") or entry_lowered.get("definitions")
        if not isinstance(senses, list) or not senses:
            continue

        for sense in senses:
            sense_def = ""
            if isinstance(sense, dict):
                lowered_sense = {str(k).lower(): v for k, v in sense.items()}
                sense_def = str(
                    lowered_sense.get("definition")
                    or lowered_sense.get("meaning")
                    or lowered_sense.get("description")
                    or ""
                ).strip()
            elif isinstance(sense, (str, int, float, bool)):
                sense_def = str(sense).strip()

            if sense_def and not _looks_like_non_word_payload(sense_def):
                return True

    return False


def _is_deep_fallback_valid(data, word, depth=0):
    """
    Strict recursive validation for DictionaryAPI.dev-style payloads.

    A valid item must match the exact word and contain dictionaries meanings
    with at least one real definition.
    """
    if depth > 50:
        return False

    if isinstance(data, list):
        if not data:
            return False
        return any(_is_deep_fallback_valid(item, word, depth + 1) for item in data)

    if not isinstance(data, dict):
        return False

    lowered = {str(k).lower(): v for k, v in data.items()}

    if not _matches_exact_word(lowered.get("word"), word):
        return False

    meanings = lowered.get("meanings")
    if not isinstance(meanings, list) or not meanings:
        return False

    for meaning in meanings:
        if not isinstance(meaning, dict):
            continue
        definitions = meaning.get("definitions")
        if not isinstance(definitions, list) or not definitions:
            continue

        for definition in definitions:
            if not isinstance(definition, dict):
                continue
            def_text = str(definition.get("definition", "")).strip()
            if def_text and not _looks_like_non_word_payload(def_text):
                return True

    return False


def _deep_validate_payload(data, word, fallback_mode=False):
    """
    Safely examine arbitrary JSON structures without crashing.
    Returns (valid, rejected_as_non_word).
    """
    try:
        if fallback_mode:
            valid = _is_deep_fallback_valid(data, word)
        else:
            valid = _is_deep_primary_valid(data, word)
        return valid, False
    except Exception:
        # An unexpected payload shape means unknown verification, never a crash.
        return False, True


async def _fetch_dictionary(url, label, word, fallback_mode=False):
    """
    Hit one dictionary API. Returns WordStatus.VALID / INVALID / ERROR.

    200 -> VALID only when payload contains a real dictionary entry with at
           least one definition for the exact requested word; otherwise INVALID.
    404 -> INVALID (word genuinely not found)
    Other HTTP / network / parse issues -> ERROR
    """
    timeout = aiohttp.ClientTimeout(total=API_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                raw = await resp.text()
                code = resp.status

                if code == 200:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        try:
                            import json as _json
                            data = _json.loads(raw or "")
                        except Exception:
                            if _looks_like_non_word_payload(raw):
                                return WordStatus.INVALID
                            print(f"[WORDCHAIN] {label} dictionary API returned invalid JSON")
                            return WordStatus.ERROR

                    valid, rejected_as_non_word = _deep_validate_payload(
                        data, word, fallback_mode=fallback_mode
                    )
                    if valid:
                        return WordStatus.VALID
                    if rejected_as_non_word:
                        print(f"[WORDCHAIN] {label} dictionary API unexpected payload")
                        return WordStatus.ERROR

                    # 200 with a concrete response but no real dictionary definition
                    # is treated as the word not being a genuine dictionary entry.
                    return WordStatus.INVALID

                if code == 404:
                    return WordStatus.INVALID

                if code in _FALLBACK_STATUSES:
                    print(f"[WORDCHAIN] {label} dictionary API HTTP {code}")
                    return WordStatus.ERROR

                print(f"[WORDCHAIN] {label} dictionary API unexpected HTTP {code}")
                return WordStatus.ERROR

    except asyncio.TimeoutError:
        print(f"[WORDCHAIN] {label} dictionary API timeout")
        return WordStatus.ERROR
    except aiohttp.ClientError as exc:
        print(f"[WORDCHAIN] {label} dictionary API connection error: {type(exc).__name__}")
        return WordStatus.ERROR
    except Exception as exc:
        # Never crash the bot because of an HTTP layer surprise
        print(f"[WORDCHAIN] {label} dictionary API unexpected error: {type(exc).__name__}")
        return WordStatus.ERROR


async def _api_validate(word):
    """
    Run primary then fallback. Exactly one request per API, no retries.

    A word is:
      VALID   -> an API returns a genuine dictionary entry with a real definition
                 for the exact word
      INVALID -> both APIs that answered say the exact word has no dictionary entry
      ERROR   -> neither API could give a definitive outcome
    """
    encoded = quote(word, safe="")

    primary = await _fetch_dictionary(
        PRIMARY_API_URL.format(encoded), "primary", word, fallback_mode=False
    )
    if primary == WordStatus.VALID:
        return WordStatus.VALID

    # Fallback only when primary genuinely could not verify the definition.
    fallback = await _fetch_dictionary(
        FALLBACK_API_URL.format(encoded), "fallback", word, fallback_mode=True
    )
    if fallback == WordStatus.VALID:
        return WordStatus.VALID

    # A word is INVALID only when both sources authoritatively say it has no
    # dictionary entry. Any temporary API failure keeps the outcome as ERROR.
    if primary == WordStatus.INVALID and fallback == WordStatus.INVALID:
        return WordStatus.INVALID

    print(f"[WORDCHAIN] both dictionary APIs unavailable for '{word}'")
    return WordStatus.ERROR


async def validate_word(raw):
    """
    Validate an English word (async, never blocks the event loop).

    Order:
      1. normalize
      2. global cache hit  -> instant answer
      3. join an in-flight identical lookup, if any
      4. primary API -> fallback API
      5. cache the definitive answer

    Returns a ValidationResult with status VALID / INVALID / ERROR.
    """
    word = normalize_word(raw)
    if word is None:
        cleaned = (str(raw).strip().lower() if raw is not None else "")
        return ValidationResult(WordStatus.INVALID, cleaned[:MAX_WORD_LENGTH] or "<empty>")

    cached = _cache.get(word)
    if cached is not None:
        return ValidationResult(
            WordStatus.VALID if cached else WordStatus.INVALID, word
        )

    # Share an identical lookup already running for another group
    pending = _pending.get(word)
    if pending is not None:
        try:
            status = await pending
        except Exception:
            status = WordStatus.ERROR
        return ValidationResult(status, word)

    task = asyncio.create_task(_api_validate(word))
    _pending[word] = task
    try:
        status = await task
    except Exception:
        status = WordStatus.ERROR
    finally:
        _pending.pop(word, None)

    # Never cache temporary failures — ERROR must allow a later retry
    if status in (WordStatus.VALID, WordStatus.INVALID):
        _cache[word] = (status == WordStatus.VALID)

    return ValidationResult(status, word)
