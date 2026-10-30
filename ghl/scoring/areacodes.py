"""Area code -> (state/region, principal area served, approx median household income $k).

Income figures are approximate ACS-era (2022-2023) median household income for
the metro or region the area code principally serves, assembled by hand. They
are directional, NOT census-exact, and an area code only says where a number
was issued -- mobile numbers travel with their owner. Treat as a soft signal.
"""
# code: (state, label, median household income in $thousands)
AC = {
# --- DC / MD / VA / DE ---
"202":("DC","Washington DC",101),"240":("MD","Montgomery/Frederick MD",115),
"301":("MD","Montgomery/Frederick MD",115),"443":("MD","Baltimore metro",90),
"410":("MD","Baltimore metro",90),"667":("MD","Baltimore metro",90),
"703":("VA","Northern Virginia",135),"571":("VA","Northern Virginia",135),
"540":("VA","Shenandoah/Roanoke VA",70),"804":("VA","Richmond VA",75),
"757":("VA","Hampton Roads VA",72),"276":("VA","Southwest Virginia",45),
"434":("VA","Central Virginia",60),"302":("DE","Delaware",80),
# --- Bay Area / NorCal ---
"408":("CA","San Jose/Silicon Valley",150),"669":("CA","San Jose/Silicon Valley",150),
"650":("CA","SF Peninsula",150),"415":("CA","San Francisco",130),"628":("CA","San Francisco",130),
"510":("CA","Oakland/Alameda",110),"341":("CA","Oakland/Alameda",110),
"925":("CA","Contra Costa/Tri-Valley",130),"707":("CA","Napa/Sonoma/Vallejo",90),
"831":("CA","Santa Cruz/Monterey",90),"916":("CA","Sacramento",80),"279":("CA","Sacramento",80),
"530":("CA","Northern CA rural",65),"209":("CA","Stockton/Modesto",70),"559":("CA","Fresno",60),
# --- SoCal ---
"213":("CA","Los Angeles city",65),"323":("CA","Los Angeles city",65),
"310":("CA","Westside LA/South Bay",105),"424":("CA","Westside LA/South Bay",105),
"818":("CA","San Fernando Valley",80),"747":("CA","San Fernando Valley",80),
"626":("CA","San Gabriel Valley",82),"562":("CA","Long Beach/SE LA",82),
"909":("CA","Inland Empire (San Bernardino)",75),"951":("CA","Riverside",82),
"714":("CA","Orange County",95),"657":("CA","Orange County",95),"949":("CA","South Orange County",120),
"619":("CA","San Diego city",82),"858":("CA","North San Diego",110),
"760":("CA","North SD county/desert",75),"442":("CA","North SD county/desert",75),
"805":("CA","Ventura/Santa Barbara",90),"661":("CA","Bakersfield/Antelope Valley",65),
# --- Pacific NW / Mountain ---
"206":("WA","Seattle",115),"425":("WA","Seattle Eastside",125),"253":("WA","Tacoma",90),
"360":("WA","Olympia/Bellingham WA",85),"509":("WA","Eastern Washington",68),
"564":("WA","Western Washington",95),"503":("OR","Portland",82),"971":("OR","Portland",82),
"541":("OR","Rural Oregon",62),"458":("OR","Rural Oregon",62),
"303":("CO","Denver",90),"720":("CO","Denver",90),"983":("CO","Denver",90),
"970":("CO","Boulder/Fort Collins/Western CO",80),"719":("CO","Colorado Springs/Pueblo",70),
"801":("UT","Salt Lake City",85),"385":("UT","Salt Lake City",85),"435":("UT","Rural Utah",72),
"208":("ID","Idaho",68),"986":("ID","Idaho",68),"406":("MT","Montana",65),"307":("WY","Wyoming",70),
"702":("NV","Las Vegas",70),"725":("NV","Las Vegas",70),"775":("NV","Reno/Rural Nevada",70),
"480":("AZ","Scottsdale/Mesa",85),"602":("AZ","Phoenix",68),"623":("AZ","West Phoenix Valley",72),
"520":("AZ","Tucson",58),"928":("AZ","Rural Arizona",55),
"505":("NM","Albuquerque/Santa Fe",58),"575":("NM","Rural New Mexico",50),
"808":("HI","Hawaii",95),"907":("AK","Alaska",88),
# --- Northeast ---
"617":("MA","Boston",95),"857":("MA","Boston",95),"781":("MA","Boston suburbs",125),
"339":("MA","Boston suburbs",125),"978":("MA","Northern Massachusetts",110),
"508":("MA","Southeastern Massachusetts",95),"774":("MA","Southeastern Massachusetts",95),
"413":("MA","Western Massachusetts",70),
"203":("CT","Fairfield/New Haven CT",95),"475":("CT","Fairfield/New Haven CT",95),
"860":("CT","Hartford CT",85),"959":("CT","Hartford CT",85),
"401":("RI","Rhode Island",85),"603":("NH","New Hampshire",95),
"207":("ME","Maine",70),"802":("VT","Vermont",75),
"201":("NJ","Bergen/Hudson NJ",105),"551":("NJ","Bergen/Hudson NJ",105),
"973":("NJ","Essex/Morris NJ",95),"862":("NJ","Essex/Morris NJ",95),
"908":("NJ","Union/Somerset NJ",105),"732":("NJ","Middlesex/Monmouth NJ",105),
"848":("NJ","Middlesex/Monmouth NJ",105),"609":("NJ","Mercer/Atlantic NJ",85),
"640":("NJ","Mercer/Atlantic NJ",85),"856":("NJ","Camden NJ",85),
"212":("NY","Manhattan",100),"646":("NY","Manhattan",100),"332":("NY","Manhattan",100),
"917":("NY","New York City (mobile)",85),"347":("NY","Brooklyn/Queens/Bronx",70),
"718":("NY","Brooklyn/Queens/Bronx",70),"929":("NY","Brooklyn/Queens/Bronx",70),
"516":("NY","Nassau County NY",130),"631":("NY","Suffolk County NY",120),"934":("NY","Suffolk County NY",120),
"914":("NY","Westchester NY",110),"845":("NY","Hudson Valley NY",95),
"518":("NY","Albany NY",75),"838":("NY","Albany NY",75),"585":("NY","Rochester NY",65),
"315":("NY","Syracuse NY",65),"680":("NY","Syracuse NY",65),"607":("NY","Binghamton/Ithaca NY",60),
"716":("NY","Buffalo NY",65),
"215":("PA","Philadelphia",75),"267":("PA","Philadelphia",75),"445":("PA","Philadelphia",75),
"610":("PA","Philadelphia suburbs",100),"484":("PA","Philadelphia suburbs",100),"835":("PA","Philadelphia suburbs",100),
"717":("PA","Lancaster/Harrisburg PA",70),"223":("PA","Lancaster/Harrisburg PA",70),
"570":("PA","Northeastern Pennsylvania",62),"272":("PA","Northeastern Pennsylvania",62),
"412":("PA","Pittsburgh",68),"878":("PA","Pittsburgh",68),"724":("PA","Western Pennsylvania",65),
"814":("PA","Central Pennsylvania",58),
# --- Midwest ---
"312":("IL","Chicago city",75),"872":("IL","Chicago city",75),"773":("IL","Chicago city",70),
"847":("IL","Chicago north suburbs",100),"224":("IL","Chicago north suburbs",100),
"630":("IL","DuPage County IL",100),"331":("IL","DuPage County IL",100),
"708":("IL","South Cook County IL",68),"815":("IL","Rockford/Joliet IL",70),"779":("IL","Rockford/Joliet IL",70),
"217":("IL","Springfield IL",62),"309":("IL","Peoria IL",60),"618":("IL","Southern Illinois",55),
"614":("OH","Columbus OH",72),"380":("OH","Columbus OH",72),"216":("OH","Cleveland",62),
"440":("OH","Cleveland suburbs",75),"330":("OH","Akron/Canton OH",62),"234":("OH","Akron/Canton OH",62),
"513":("OH","Cincinnati",70),"283":("OH","Cincinnati",70),"937":("OH","Dayton OH",62),
"419":("OH","Toledo OH",58),"567":("OH","Toledo OH",58),"740":("OH","Southeastern Ohio",58),
"313":("MI","Detroit city",45),"248":("MI","Oakland County MI",95),"947":("MI","Oakland County MI",95),
"586":("MI","Macomb County MI",72),"734":("MI","Ann Arbor MI",82),"810":("MI","Flint MI",58),
"616":("MI","Grand Rapids MI",72),"269":("MI","Kalamazoo MI",62),"517":("MI","Lansing MI",65),
"231":("MI","Northern Michigan",58),"906":("MI","Upper Peninsula MI",55),"989":("MI","Central Michigan",58),
"414":("WI","Milwaukee",60),"262":("WI","Waukesha WI",85),"920":("WI","Green Bay/Appleton WI",68),
"608":("WI","Madison WI",75),"715":("WI","Northern Wisconsin",60),"534":("WI","Northern Wisconsin",60),
"612":("MN","Minneapolis",75),"651":("MN","St Paul MN",78),"763":("MN","Minneapolis north suburbs",95),
"952":("MN","Minneapolis south suburbs",105),"507":("MN","Southern Minnesota",70),"218":("MN","Northern Minnesota",60),
"515":("IA","Des Moines IA",75),"319":("IA","Cedar Rapids IA",68),"563":("IA","Davenport IA",65),
"641":("IA","Rural Iowa",62),"712":("IA","Western Iowa",62),
"402":("NE","Omaha/Lincoln NE",72),"531":("NE","Omaha/Lincoln NE",72),"308":("NE","Western Nebraska",62),
"605":("SD","South Dakota",65),"701":("ND","North Dakota",70),
"816":("MO","Kansas City MO",65),"975":("MO","Kansas City MO",65),"636":("MO","St Charles MO",90),
"314":("MO","St Louis",60),"573":("MO","Rural Missouri",55),"417":("MO","Springfield MO",55),
"660":("MO","Rural Missouri",55),
"913":("KS","Johnson County KS",95),"316":("KS","Wichita KS",62),"785":("KS","Topeka/Lawrence KS",65),
"620":("KS","Southern Kansas",58),
"317":("IN","Indianapolis",68),"463":("IN","Indianapolis",68),"219":("IN","Northwest Indiana",62),
"574":("IN","North Central Indiana",60),"260":("IN","Fort Wayne IN",60),"765":("IN","Central Indiana",58),
"812":("IN","Southern Indiana",60),"930":("IN","Southern Indiana",60),
# --- South Atlantic ---
"404":("GA","Atlanta city",75),"470":("GA","Atlanta suburbs",85),"678":("GA","Atlanta suburbs",85),
"770":("GA","Atlanta suburbs",85),"943":("GA","Atlanta suburbs",85),
"706":("GA","North/East Georgia",58),"762":("GA","North/East Georgia",58),"912":("GA","Savannah GA",62),
"229":("GA","Southwest Georgia",50),"478":("GA","Macon GA",52),
"305":("FL","Miami",60),"786":("FL","Miami",60),"954":("FL","Broward County FL",68),"754":("FL","Broward County FL",68),
"561":("FL","Palm Beach FL",75),"772":("FL","Treasure Coast FL",68),
"407":("FL","Orlando",70),"689":("FL","Orlando",70),"321":("FL","Space Coast FL",70),
"813":("FL","Tampa",70),"656":("FL","Tampa",70),"727":("FL","Pinellas County FL",68),
"941":("FL","Sarasota FL",72),"239":("FL","Naples/Fort Myers FL",75),
"904":("FL","Jacksonville FL",70),"352":("FL","North Central Florida",58),
"850":("FL","Florida Panhandle",62),"863":("FL","Interior Florida",58),"386":("FL","Daytona FL",58),
"704":("NC","Charlotte",75),"980":("NC","Charlotte",75),"919":("NC","Raleigh-Durham",85),"984":("NC","Raleigh-Durham",85),
"336":("NC","Greensboro/Winston-Salem NC",62),"743":("NC","Greensboro/Winston-Salem NC",62),
"252":("NC","Eastern North Carolina",52),"828":("NC","Asheville/Western NC",58),
"910":("NC","Fayetteville/Wilmington NC",58),
"803":("SC","Columbia SC",62),"839":("SC","Columbia SC",62),"843":("SC","Charleston/Coastal SC",68),
"854":("SC","Charleston/Coastal SC",68),"864":("SC","Greenville SC",62),
"304":("WV","West Virginia",52),"681":("WV","West Virginia",52),
# --- South Central ---
"615":("TN","Nashville",75),"629":("TN","Nashville",75),"901":("TN","Memphis",50),
"865":("TN","Knoxville TN",62),"423":("TN","Chattanooga/Tri-Cities TN",58),
"931":("TN","Rural Tennessee",58),"731":("TN","West Tennessee",48),
"502":("KY","Louisville KY",62),"859":("KY","Lexington/Northern KY",65),
"270":("KY","Western Kentucky",55),"364":("KY","Western Kentucky",55),"606":("KY","Eastern Kentucky",40),
"205":("AL","Birmingham AL",62),"659":("AL","Birmingham AL",62),"251":("AL","Mobile AL",55),
"256":("AL","Huntsville AL",70),"938":("AL","Huntsville AL",70),"334":("AL","Montgomery AL",52),
"601":("MS","Jackson MS",50),"769":("MS","Jackson MS",50),"228":("MS","Mississippi Gulf Coast",55),
"662":("MS","Northern Mississippi",45),
"504":("LA","New Orleans",50),"985":("LA","New Orleans suburbs",62),"225":("LA","Baton Rouge LA",60),
"337":("LA","Lafayette LA",55),"318":("LA","Northern Louisiana",48),
"501":("AR","Little Rock AR",62),"479":("AR","Northwest Arkansas",65),"870":("AR","Rural Arkansas",48),
"405":("OK","Oklahoma City",62),"572":("OK","Oklahoma City",62),"918":("OK","Tulsa OK",60),
"539":("OK","Tulsa OK",60),"580":("OK","Southern Oklahoma",55),
# --- Texas ---
"214":("TX","Dallas",82),"469":("TX","Dallas",82),"945":("TX","Dallas",82),"972":("TX","Dallas suburbs",95),
"817":("TX","Fort Worth",78),"682":("TX","Fort Worth",78),
"713":("TX","Houston",72),"281":("TX","Houston",72),"832":("TX","Houston",72),"346":("TX","Houston",72),
"512":("TX","Austin",90),"737":("TX","Austin",90),"210":("TX","San Antonio",68),"726":("TX","San Antonio",68),
"915":("TX","El Paso TX",55),"956":("TX","Rio Grande Valley TX",48),"361":("TX","Corpus Christi TX",58),
"409":("TX","Beaumont TX",60),"903":("TX","Northeast Texas",58),"430":("TX","Northeast Texas",58),
"940":("TX","North Texas",65),"254":("TX","Waco/Killeen TX",60),"325":("TX","Abilene TX",58),
"432":("TX","Midland/Odessa TX",72),"806":("TX","Lubbock/Amarillo TX",60),
"979":("TX","Bryan/College Station TX",62),"830":("TX","Texas Hill Country",62),"936":("TX","East Texas",58),
# --- Non-US / non-geographic ---
"787":("PR","Puerto Rico",25),"939":("PR","Puerto Rico",25),
"416":("CA-ON","Toronto",None),"647":("CA-ON","Toronto",None),"437":("CA-ON","Toronto",None),
"905":("CA-ON","Greater Toronto",None),"289":("CA-ON","Greater Toronto",None),"365":("CA-ON","Greater Toronto",None),
"519":("CA-ON","Southwestern Ontario",None),"226":("CA-ON","Southwestern Ontario",None),
"613":("CA-ON","Ottawa",None),"343":("CA-ON","Ottawa",None),"705":("CA-ON","Northern Ontario",None),
"807":("CA-ON","Northwestern Ontario",None),
"514":("CA-QC","Montreal",None),"438":("CA-QC","Montreal",None),"450":("CA-QC","Montreal area",None),
"418":("CA-QC","Quebec City",None),"819":("CA-QC","Quebec",None),
"604":("CA-BC","Vancouver",None),"778":("CA-BC","British Columbia",None),"250":("CA-BC","British Columbia",None),
"236":("CA-BC","British Columbia",None),
"403":("CA-AB","Calgary",None),"587":("CA-AB","Alberta",None),"780":("CA-AB","Edmonton",None),
"825":("CA-AB","Alberta",None),"306":("CA-SK","Saskatchewan",None),"204":("CA-MB","Manitoba",None),
"902":("CA-NS","Nova Scotia",None),"506":("CA-NB","New Brunswick",None),"709":("CA-NL","Newfoundland",None),
"876":("JM","Jamaica",None),
"800":("TOLLFREE","Toll-free (not a person)",None),"888":("TOLLFREE","Toll-free (not a person)",None),
"877":("TOLLFREE","Toll-free (not a person)",None),"866":("TOLLFREE","Toll-free (not a person)",None),
"855":("TOLLFREE","Toll-free (not a person)",None),"844":("TOLLFREE","Toll-free (not a person)",None),
"833":("TOLLFREE","Toll-free (not a person)",None),
}
# overlay codes that share a region with an existing code
AC.setdefault("448",("FL","Florida Panhandle",62))
AC.setdefault("728",("FL","Interior Florida",58))
AC.setdefault("621",("FL","Florida",65))
AC.setdefault("220",("OH","Southeastern Ohio",58))
AC.setdefault("840",("CA","Inland Empire (San Bernardino)",75))
AC.setdefault("320",("MN","Central Minnesota",65))
AC.setdefault("351",("MA","Northern Massachusetts",110))
AC.setdefault("820",("CA","Ventura/Santa Barbara",90))
AC.setdefault("326",("OH","Dayton OH",62))
AC.setdefault("464",("IL","South Cook County IL",68))
AC.setdefault("123",("INVALID","Invalid area code",None))

def tier(inc):
    if inc is None: return "?"
    if inc >= 95: return "A"
    if inc >= 78: return "B"
    if inc >= 62: return "C"
    return "D"

def lookup(phone):
    """-> (code, state, label, income_k, tier)"""
    if not phone or not phone.startswith("+1") or len(phone) != 12:
        return (None, "NON-US", "Non-US or malformed number", None, "?")
    c = phone[2:5]
    st, lab, inc = AC.get(c, (None, None, None))
    if st is None:
        return (c, "US?", "Unmapped US area code", None, "?")
    return (c, st, lab, inc, tier(inc))
