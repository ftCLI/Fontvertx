PS_SFNT_VERSION = "OTTO"
TT_SFNT_VERSION = "\0\1\0\0"
TRUE_SFNT_VERSION = "true"  # legacy Mac TrueType

WOFF_FLAVOR = "woff"
WOFF2_FLAVOR = "woff2"
OTF_EXTENSION = ".otf"
TTF_EXTENSION = ".ttf"
WOFF_EXTENSION = ".woff"
WOFF2_EXTENSION = ".woff2"

MIN_UPM = 16
MAX_UPM = 16384

# name table (platformID, encodingID, languageID) tuples
WINDOWS_EN_US = (3, 1, 0x409)  # Windows, Unicode BMP, English (US)
MAC_ROMAN_ENGLISH = (1, 0, 0)  # Macintosh, Roman, English

# head.macStyle bits
MAC_STYLE_ITALIC = 0b10

# Table tags
T_CFF = "CFF "
T_DSIG = "DSIG"
T_FVAR = "fvar"
T_GLYF = "glyf"
T_HEAD = "head"
T_HMTX = "hmtx"
T_LOCA = "loca"
T_MAXP = "maxp"
T_NAME = "name"
T_OS_2 = "OS/2"
T_POST = "post"
T_VORG = "VORG"
