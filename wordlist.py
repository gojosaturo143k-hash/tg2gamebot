"""
English word dictionary for word-based games.

Loading strategy:
  1. Try to load a system dictionary (Linux/macOS ship one) for maximum coverage.
  2. Always merge in the bundled common-word list below.
  3. Accept common inflections (plurals, -ing, -ed, ...) derived from base words.

No external dependencies required.
"""

import os

# Common system dictionary locations (present on most Linux/macOS images)
_SYSTEM_DICT_PATHS = (
    "/usr/share/dict/words",
    "/usr/share/dict/american-english",
    "/usr/share/dict/british-english",
    "/usr/dict/words",
)

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

# Suffixes we accept when derived from a known base word
_SUFFIX_RULES = (
    # (suffix, list of possible base reconstructions)
    ("s", lambda s: [s[:-1]]),
    ("es", lambda s: [s[:-2], s[:-1]]),
    ("ies", lambda s: [s[:-3] + "y"]),
    ("ed", lambda s: [s[:-2], s[:-1], s[:-3] + s[-3] if len(s) > 3 else s[:-2]]),
    ("ied", lambda s: [s[:-3] + "y"]),
    ("ing", lambda s: [s[:-3], s[:-3] + "e", s[:-4] if len(s) > 4 else s[:-3]]),
    ("er", lambda s: [s[:-2], s[:-1]]),
    ("est", lambda s: [s[:-3], s[:-2]]),
    ("ly", lambda s: [s[:-2]]),
    ("ers", lambda s: [s[:-3], s[:-2]]),
    ("ings", lambda s: [s[:-4], s[:-4] + "e"]),
)

WORDS = set()
_LETTER_COUNTS = {}


def _load():
    """Load the dictionary once at import time."""
    global WORDS, _LETTER_COUNTS

    words = set()

    # 1. Bundled baseline
    for w in _BUNDLED.split():
        w = w.strip().lower()
        if len(w) >= 2 and w.isalpha():
            words.add(w)

    # 2. System dictionary (huge boost when available)
    for path in _SYSTEM_DICT_PATHS:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        w = line.strip().lower()
                        if len(w) >= 2 and w.isalpha():
                            words.add(w)
                break  # one system dict is enough
        except Exception:
            continue

    WORDS = words

    counts = {}
    for w in words:
        c = w[0]
        counts[c] = counts.get(c, 0) + 1
    _LETTER_COUNTS = counts


_load()


def is_valid_word(word):
    """
    Return True if `word` is a valid English word.
    Accepts direct matches plus common inflections of known base words.
    """
    if not word:
        return False

    w = word.strip().lower()

    if len(w) < 2 or not w.isalpha():
        return False

    if w in WORDS:
        return True

    # Try common inflections against known base words
    for suffix, builder in _SUFFIX_RULES:
        if w.endswith(suffix) and len(w) > len(suffix) + 1:
            try:
                candidates = builder(w)
            except Exception:
                continue
            for base in candidates:
                if base and len(base) >= 2 and base in WORDS:
                    return True

    return False


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
