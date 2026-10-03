"""Assign each tune a musical tradition ("genre").

Evidence, strongest first:
  1. the tune's O: (origin) field, e.g. "Ireland", "Dalarna, Sweden"
  2. a tune type that belongs to one tradition (R:polska, R:strathspey, R:bourree, ...)
  3. the folder or site it came from (most collections stick to one tradition)
  4. weaker tune types (R:minuet, R:allemande, ...) that only decide when nothing else does
"""
import re

GENRES = {
    'irish': 'Irish',
    'scottish': 'Scottish & Cape Breton',
    'english': 'English & Welsh',
    'american': 'Old-time & North American',
    'nordic': 'Swedish & Nordic',
    'french': 'French & Breton',
    'european': 'Central & Western European',
    'balkan': 'Balkan, Klezmer & Eastern European',
    'early': 'Early Music & Classical',
    'australian': 'Australian',
    'other': 'Other',
}

ORIGINS = [
    ('irish', r'ireland|irish|irlande|\beire\b|hibern|donegal|\bclare\b|kerry|sligo|munster|connacht|leitrim|galway'),
    ('scottish', r'scotland|scottish|\bscots?\b|[ée]cosse|shetland|orkney|cape breton|hebrides|highlands|caledon'),
    ('nordic', r'sweden|swedish|sverige|su[eè]de|norw|norge|danmark|denmark|danish|dansk|finland|suomi|iceland|'
               r'scandinav|dalarna|v.?.?rmland|sk.?.?ne\b|sm.?.?land|.?.?sterg.?.?tland|h.?.?lsingland|j.?.?mtland|uppland'),
    ('american', r'\busa\b|u\.s\.a|america|appalach|kentucky|virginia|tennessee|carolina|missouri|texas|ohio|'
                 r'georgia|new england|qu.?.?bec|canada|newfoundland|ontario|catskill|shaker'),
    ('english', r'england|english|angleterre|\bwales\b|welsh|northumbr|yorkshire|lancashire|cornwall|cornish|'
                r'london|playford|sussex|kent\b|norfolk|lincolnshire|cotswold'),
    ('french', r'france|french|fran[cç]ais|bretagne|brittany|breizh|auvergne|\bberry\b|limousin|gascogne|provence|'
               r'occitan|alsace|poitou|morvan|bourbonnais'),
    ('balkan', r'bulgar|romania|hungar|greece|greek|turk|kurd|macedon|serbia|croat|bosnia|albania|klezmer|'
               r'jewish|hassid|israel|russia|ukrain|armenia|yiddish'),
    ('european', r'deutschland|germany|german|mitteleuropa|lothringen|luxemb|schweiz|switzerland|suisse|'
                 r'.?sterreich|austria|tirol|italia|italy|italie|spain|espa|galicia|asturias|portugal|'
                 r'nederland|holland|dutch|flem|flandr|belgi|poland|polen|czech|slovak|europa'),
    ('australian', r'australia|new south wales|\bnsw\b|queensland|tasmania|new zealand'),
]

STRONG_TYPES = [
    ('nordic', r'polska|engelska|hambo|halling|springar|springleik|gangar|\bpols\b|brudmarsch|brudl.t|'
               r'polon.s|reinlender|schottis\b|langdans'),
    ('irish', r'\bslides?\b|set dance'),
    ('scottish', r'strathspey|pibroch|piobaireachd'),
    ('english', r'three[- ]?two|morris|country[- ]dance'),
    ('french', r'bourr|an[- ]dro|hanter|gavot|larid|plinn|\brondeau|farandol|avant[- ]?deux|cercle|chapelloise'),
    ('balkan', r'\bhora\b|kolo\b|kopani|r.?.?[cč]enica|rachenitsa|horo\b|sirba|freylekh|bulgar|[cč]o[cč]ek|'
               r'csardas|syrt|kalamatian|pravo|daichovo|paidushko|lesnoto'),
    ('european', r'jodel|juuz|juiz|l.?.?ndler|steirer|zwiefach|walzer'),
    ('american', r'breakdown|\brag\b|two[- ]?step|old[- ]?time|contra\b|cakewalk'),
]

WEAK_TYPES = [
    ('early', r'pavan|galliard|gaillard|basse[- ]?dan|branle|bransle|canzon|allemand|courante|sarabande|'
              r'minuet|menuet|gigue|fantasia|motet|madrigal|choral|fugue|sonata|prelude|canon\b'),
]

# Folder defaults, by path prefix below sources/. Longest matching prefix wins.
FOLDERS = {
    # Sites dedicated to one tradition.
    'capeirish-com/': 'irish', 'oldmusicproject-com/': 'irish', 'pacholo-com/': 'irish',
    'lesession-co-uk/': 'irish', 'slainte-ch/': 'irish', 'fiddletech-com/': 'irish',
    'oflahertyretreat-org/': 'irish', 'novasession-org/': 'irish', 'ellwood-org/': 'irish',
    'alan-ng-net/': 'irish', 'users-wpi-edu/': 'irish', 'cobb-ece-wisc-edu/': 'irish',
    'idiot-dog-com/': 'irish', 'sessionite-com/': 'irish', 'ceolas/': 'irish', 'norbeck/i/': 'irish',
    'campin-me-uk/': 'scottish', 'cranfordpub-com/': 'scottish',
    'cpartington-plus-com/': 'english', 'colinhume-com/': 'english', 'hardy/': 'english',
    'joe-offer-com/': 'english', 'maryanahata-co-uk/': 'english', 'maryhumphreys-co-uk/': 'english',
    'themorrisring-org/': 'english', 'bassett-street-hounds-org/': 'english', 'ucolick-org/': 'english',
    'singdanceandplay-net/': 'english', 'almeleysteadysession-wordpress-com/': 'english',
    'altonsteadysession-wordpress-com/': 'english', 'thedorkingsessions-wordpress-com/': 'english',
    'cl-cam-ac-uk/': 'english', 'andrewswaine-uk/': 'english', 'nottingham/': 'english',
    'github-com/Gubbledenut/': 'english',
    'spuds-thursdaycontra-com/': 'american', 'leedscontra-freeuk-com/': 'american',
    'fifedrum-org/': 'american', 'cs-uky-edu/': 'american', 'math-dartmouth-edu/': 'american',
    'domren-free-fr/': 'american',
    'norbeck/s/': 'nordic', 'bluerose-karenlmyers-org/': 'nordic',
    'anamnese-online-fr/': 'french', 'michel-bellon-free-fr/': 'french', 'cambridgefolk-org-uk/': 'french',
    'termen-free-fr/': 'french', 'celticscores-com/': 'french', 'partitions-bzh/': 'french',
    'hurdy-gurdy-org-uk/': 'french',
    'ifdo-ca/': 'european', 'dropbox-com/': 'european', 'simonwascher-info/': 'european',
    'tapazovaldoten-altervista-org/': 'european', 'cumbriagaitaband-co-uk/': 'european',
    'natura-di-uminho-pt/': 'european',
    'voluntocracy-org/': 'balkan',
    'serpent-serpentpublications-org/': 'early', 'serpentpublications-org/': 'early',
    'graner-name/': 'early', 'alijc-github-io/': 'early', 'moinejf-free-fr/': 'early',
    'abcplus-sourceforge-net/': 'early', 'wiki-score-org/': 'early',
    'austradmusic-au/': 'australian', 'sdarby-au/': 'australian',
    # JC's archive, by printed collection.
    'jc/Playford/': 'english', 'jc/JohnWalsh/': 'english', 'jc/DftY/': 'english', 'jc/JohnJohnson/': 'english',
    'jc/DanielWright/': 'english', 'jc/NorthumbrianMinstrelsy/': 'english', 'jc/Chappell/': 'english',
    'jc/Gallini/': 'english', 'jc/OldEnglishCountryDances/': 'english', 'jc/24CountryDances/': 'english',
    'jc/KittyBridges/': 'english', 'jc/Straight_Skillern/': 'english',
    'jc/Hamilton/': 'scottish', 'jc/Kohlers/': 'scottish', 'jc/SCD/': 'scottish', 'jc/RobertPetrie/': 'scottish',
    'jc/CaledonianMusicalRepository/': 'scottish', 'jc/RobertBremner/': 'scottish', 'jc/Pringle/': 'scottish',
    'jc/AndersonsBudgetV1/': 'scottish', 'jc/AbrahamMackintosh/': 'scottish', 'jc/JohnFrench/': 'scottish',
    'jc/Kerr/': 'scottish', 'jc/Athole/': 'scottish', 'jc/JamesOswald/': 'scottish', 'jc/Aird/': 'scottish',
    'jc/Gow/': 'scottish', 'jc/Fraser/': 'scottish', 'jc/Barsanti/': 'scottish',
    'jc/CaledonianCountryDances/': 'scottish', 'jc/BonAccordCollection/': 'scottish',
    'jc/OFPC/': 'irish', 'jc/ONeills/': 'irish', 'jc/oneills/': 'irish', 'jc/CuzTeahan/': 'irish',
    'jc/HibernianMuse/': 'irish', 'jc/Rinnci_na_hEireann/': 'irish',
    'jc/EliasHowe/': 'american', 'jc/BostonCollection/': 'american', 'jc/JeanWhite/': 'american',
    'jc/HillCountryTunes/': 'american', 'jc/ryan-cole/': 'american', 'jc/CDSS/': 'american',
    'jc/AtteJensen/': 'nordic', 'jc/Landrin/': 'french',
}


def _match(rules, text):
    lower = text.lower()
    for genre, pattern in rules:
        if re.search(pattern, lower):
            return genre
    return None


def folder_genre(relative_path):
    best = ''
    for prefix in FOLDERS:
        if relative_path.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return FOLDERS.get(best)


def genre(origins, rhythm, relative_path):
    """origins: the tune's O: values; relative_path: file path below sources/."""
    return (_match(ORIGINS, ' '.join(origins)) or _match(STRONG_TYPES, rhythm)
            or folder_genre(relative_path) or _match(WEAK_TYPES, rhythm) or 'other')
