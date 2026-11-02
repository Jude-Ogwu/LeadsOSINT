"""
Intelligent US Location Normalizer for LeadsOSINT.
Converts addresses, neighborhoods, cities without states, and zip codes
into standardized 'City, ST' and valid FastPeopleSearch URL slugs.
"""
import re

# Comprehensive US States & Abbreviations
US_STATES = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT', 'delaware': 'DE',
    'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID',
    'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS',
    'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN', 'mississippi': 'MS',
    'missouri': 'MO', 'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH', 'oklahoma': 'OK',
    'oregon': 'OR', 'pennsylvania': 'PA', 'rhode island': 'RI', 'south carolina': 'SC',
    'south dakota': 'SD', 'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT',
    'vermont': 'VT', 'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY', 'district of columbia': 'DC', 'dc': 'DC',
    'puerto rico': 'PR', 'guam': 'GU', 'virgin islands': 'VI'
}
STATE_CODES = set(US_STATES.values())

# Well-known US areas / neighborhoods to City, ST
NEIGHBORHOOD_MAP = {
    'logan circle': ('Washington', 'DC'),
    'dupont circle': ('Washington', 'DC'),
    'adams morgan': ('Washington', 'DC'),
    'georgetown': ('Washington', 'DC'),
    'capitol hill': ('Washington', 'DC'),
    'foggy bottom': ('Washington', 'DC'),
    'brooklyn': ('Brooklyn', 'NY'),
    'manhattan': ('New York', 'NY'),
    'queens': ('Queens', 'NY'),
    'bronx': ('Bronx', 'NY'),
    'staten island': ('Staten Island', 'NY'),
    'harlem': ('New York', 'NY'),
    'soho': ('New York', 'NY'),
    'tribeca': ('New York', 'NY'),
    'hollywood': ('Los Angeles', 'CA'),
    'beverly hills': ('Beverly Hills', 'CA'),
    'buckhead': ('Atlanta', 'GA'),
    'south beach': ('Miami Beach', 'FL'),
    'brickell': ('Miami', 'FL'),
    'downtown la': ('Los Angeles', 'CA'),
    'silicon valley': ('San Jose', 'CA'),
}

# Major US Cities mapping without state specified
MAJOR_CITIES = {
    'winston salem': ('Winston-Salem', 'NC'),
    'winston-salem': ('Winston-Salem', 'NC'),
    'new york': ('New York', 'NY'),
    'los angeles': ('Los Angeles', 'CA'),
    'chicago': ('Chicago', 'IL'),
    'houston': ('Houston', 'TX'),
    'phoenix': ('Phoenix', 'AZ'),
    'philadelphia': ('Philadelphia', 'PA'),
    'san antonio': ('San Antonio', 'TX'),
    'san diego': ('San Diego', 'CA'),
    'dallas': ('Dallas', 'TX'),
    'austin': ('Austin', 'TX'),
    'san jose': ('San Jose', 'CA'),
    'fort worth': ('Fort Worth', 'TX'),
    'jacksonville': ('Jacksonville', 'FL'),
    'columbus': ('Columbus', 'OH'),
    'charlotte': ('Charlotte', 'NC'),
    'indianapolis': ('Indianapolis', 'IN'),
    'san francisco': ('San Francisco', 'CA'),
    'seattle': ('Seattle', 'WA'),
    'denver': ('Denver', 'CO'),
    'oklahoma city': ('Oklahoma City', 'OK'),
    'nashville': ('Nashville', 'TN'),
    'el paso': ('El Paso', 'TX'),
    'washington': ('Washington', 'DC'),
    'las vegas': ('Las Vegas', 'NV'),
    'boston': ('Boston', 'MA'),
    'portland': ('Portland', 'OR'),
    'louisville': ('Louisville', 'KY'),
    'memphis': ('Memphis', 'TN'),
    'detroit': ('Detroit', 'MI'),
    'baltimore': ('Baltimore', 'MD'),
    'milwaukee': ('Milwaukee', 'WI'),
    'albuquerque': ('Albuquerque', 'NM'),
    'tucson': ('Tucson', 'AZ'),
    'fresno': ('Fresno', 'CA'),
    'sacramento': ('Sacramento', 'CA'),
    'kansas city': ('Kansas City', 'MO'),
    'mesa': ('Mesa', 'AZ'),
    'atlanta': ('Atlanta', 'GA'),
    'omaha': ('Omaha', 'NE'),
    'colorado springs': ('Colorado Springs', 'CO'),
    'raleigh': ('Raleigh', 'NC'),
    'long beach': ('Long Beach', 'CA'),
    'virginia beach': ('Virginia Beach', 'VA'),
    'miami': ('Miami', 'FL'),
    'minneapolis': ('Minneapolis', 'MN'),
    'tulsa': ('Tulsa', 'OK'),
    'tampa': ('Tampa', 'FL'),
    'arlington': ('Arlington', 'TX'),
    'new orleans': ('New Orleans', 'LA'),
    'wichita': ('Wichita', 'KS'),
    'cleveland': ('Cleveland', 'OH'),
    'bakersfield': ('Bakersfield', 'CA'),
    'aurora': ('Aurora', 'CO'),
    'anaheim': ('Anaheim', 'CA'),
    'honolulu': ('Honolulu', 'HI'),
    'santa ana': ('Santa Ana', 'CA'),
    'riverside': ('Riverside', 'CA'),
    'corpus christi': ('Corpus Christi', 'TX'),
    'lexington': ('Lexington', 'KY'),
    'stockton': ('Stockton', 'CA'),
    'henderson': ('Henderson', 'NV'),
    'saint paul': ('Saint Paul', 'MN'),
    'st louis': ('St. Louis', 'MO'),
    'st. louis': ('St. Louis', 'MO'),
    'cincinnati': ('Cincinnati', 'OH'),
    'pittsburgh': ('Pittsburgh', 'PA'),
    'greensboro': ('Greensboro', 'NC'),
    'anchorage': ('Anchorage', 'AK'),
    'plano': ('Plano', 'TX'),
    'orlando': ('Orlando', 'FL'),
    'irvine': ('Irvine', 'CA'),
    'newark': ('Newark', 'NJ'),
    'durham': ('Durham', 'NC'),
    'chula vista': ('Chula Vista', 'CA'),
    'toledo': ('Toledo', 'OH'),
    'fort wayne': ('Fort Wayne', 'IN'),
    'st petersburg': ('St. Petersburg', 'FL'),
    'laredo': ('Laredo', 'TX'),
    'jersey city': ('Jersey City', 'NJ'),
    'chandler': ('Chandler', 'AZ'),
    'madison': ('Madison', 'WI'),
    'lubbock': ('Lubbock', 'TX'),
    'scottsdale': ('Scottsdale', 'AZ'),
    'reno': ('Reno', 'NV'),
    'buffalo': ('Buffalo', 'NY'),
    'gilbert': ('Gilbert', 'AZ'),
    'glendale': ('Glendale', 'AZ'),
    'north las vegas': ('North Las Vegas', 'NV'),
    'norfolk': ('Norfolk', 'VA'),
    'chesapeake': ('Chesapeake', 'VA'),
    'garland': ('Garland', 'TX'),
    'irving': ('Irving', 'TX'),
    'hialeah': ('Hialeah', 'FL'),
    'fremont': ('Fremont', 'CA'),
    'boise': ('Boise', 'ID'),
    'richmond': ('Richmond', 'VA'),
    'baton rouge': ('Baton Rouge', 'LA'),
    'spokane': ('Spokane', 'WA'),
    'des moines': ('Des Moines', 'IA'),
    'tacoma': ('Tacoma', 'WA'),
    'san bernardino': ('San Bernardino', 'CA'),
    'modesto': ('Modesto', 'CA'),
    'fontana': ('Fontana', 'CA'),
    'santa clarita': ('Santa Clarita', 'CA'),
    'birmingham': ('Birmingham', 'AL'),
    'oxnard': ('Oxnard', 'CA'),
    'fayetteville': ('Fayetteville', 'NC'),
    'rochester': ('Rochester', 'NY'),
    'moreno valley': ('Moreno Valley', 'CA'),
    'huntington beach': ('Huntington Beach', 'CA'),
    'salt lake city': ('Salt Lake City', 'UT'),
    'grand rapids': ('Grand Rapids', 'MI'),
    'amarillo': ('Amarillo', 'TX'),
    'yonkers': ('Yonkers', 'NY'),
    'montgomery': ('Montgomery', 'AL'),
    'akron': ('Akron', 'OH'),
    'little rock': ('Little Rock', 'AR'),
    'huntsville': ('Huntsville', 'AL'),
    'augusta': ('Augusta', 'GA'),
    'port st lucie': ('Port St. Lucie', 'FL'),
    'grand prairie': ('Grand Prairie', 'TX'),
    'tallahassee': ('Tallahassee', 'FL'),
    'overland park': ('Overland Park', 'KS'),
    'tempe': ('Tempe', 'AZ'),
    'mckinney': ('McKinney', 'TX'),
    'mobile': ('Mobile', 'AL'),
    'cape coral': ('Cape Coral', 'FL'),
    'shreveport': ('Shreveport', 'LA'),
    'frisco': ('Frisco', 'TX'),
    'knoxville': ('Knoxville', 'TN'),
    'worcester': ('Worcester', 'MA'),
    'brownsville': ('Brownsville', 'TX'),
    'vancouver': ('Vancouver', 'WA'),
    'fort lauderdale': ('Fort Lauderdale', 'FL'),
    'sioux falls': ('Sioux Falls', 'SD'),
    'ontario': ('Ontario', 'CA'),
    'chattanooga': ('Chattanooga', 'TN'),
    'providence': ('Providence', 'RI'),
    'newport news': ('Newport News', 'VA'),
    'rancho cucamonga': ('Rancho Cucamonga', 'CA'),
    'santa rosa': ('Santa Rosa', 'CA'),
    'peoria': ('Peoria', 'AZ'),
    'oceanside': ('Oceanside', 'CA'),
    'elk grove': ('Elk Grove', 'CA'),
    'salem': ('Salem', 'OR'),
    'pembroke pines': ('Pembroke Pines', 'FL'),
    'eugene': ('Eugene', 'OR'),
    'garden grove': ('Garden Grove', 'CA'),
    'cary': ('Cary', 'NC'),
    'fort collins': ('Fort Collins', 'CO'),
    'corona': ('Corona', 'CA'),
    'springfield': ('Springfield', 'MO'),
    'jackson': ('Jackson', 'MS'),
    'alexandria': ('Alexandria', 'VA'),
    'hayward': ('Hayward', 'CA'),
    'lancaster': ('Lancaster', 'CA'),
    'lakewood': ('Lakewood', 'CO'),
    'clarksville': ('Clarksville', 'TN'),
    'palmdale': ('Palmdale', 'CA'),
    'salinas': ('Salinas', 'CA'),
    'hollywood fl': ('Hollywood', 'FL'),
    'pasadena': ('Pasadena', 'TX'),
    'sunnyvale': ('Sunnyvale', 'CA'),
    'macon': ('Macon', 'GA'),
    'pomona': ('Pomona', 'CA'),
    'escondido': ('Escondido', 'CA'),
    'killeen': ('Killeen', 'TX'),
    'naperville': ('Naperville', 'IL'),
    'joliet': ('Joliet', 'IL'),
    'bellevue': ('Bellevue', 'WA'),
    'rockford': ('Rockford', 'IL'),
    'savannah': ('Savannah', 'GA'),
    'paterson': ('Paterson', 'NJ'),
    'torrance': ('Torrance', 'CA'),
    'bridgeport': ('Bridgeport', 'CT'),
    'mcallen': ('McAllen', 'TX'),
    'mesquite': ('Mesquite', 'TX'),
    'syracuse': ('Syracuse', 'NY'),
    'midland': ('Midland', 'TX'),
    'murfreesboro': ('Murfreesboro', 'TN'),
    'miramar': ('Miramar', 'FL'),
    'dayton': ('Dayton', 'OH'),
    'fullerton': ('Fullerton', 'CA'),
    'olathe': ('Olathe', 'KS'),
    'orange': ('Orange', 'CA'),
    'thornton': ('Thornton', 'CO'),
    'roseville': ('Roseville', 'CA'),
    'denton': ('Denton', 'TX'),
    'waco': ('Waco', 'TX'),
    'surprise': ('Surprise', 'AZ'),
    'carrollton': ('Carrollton', 'TX'),
    'charleston': ('Charleston', 'SC'),
    'carmel': ('Carmel', 'IN'),
    'rockville': ('Rockville', 'MD'),
    'coral gables': ('Coral Gables', 'FL')
}

STREET_PREFIXES = r'\b(?:\d+[\w-]*\s+)?(?:north|south|east|west|n|s|e|w|nw|ne|sw|se)?\s*(?:[a-zA-Z0-9\s]+?)\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|blvd|boulevard|way|court|ct|circle|cir|terrace|ter|place|pl|parkway|pkwy|loop|hwy|highway|route|rt|unit|apt|suite|ste|bldg|#)\b'

def normalize_location(raw_loc):
    """
    Takes an input location string (which could be a street address,
    neighborhood, city without state, city with state, or zip code),
    and returns a tuple of (display_location, url_slug).
    
    Examples:
      'Winston Salem' -> ('Winston-Salem, NC', 'winston-salem-nc')
      'Logan Circle' -> ('Washington, DC', 'washington-dc')
      '1515 Q St NW, Washington, DC' -> ('Washington, DC', 'washington-dc')
      'Rockville MD 20850' -> ('Rockville, MD', 'rockville-md')
      'FL' -> ('Florida', 'fl')
      '27101' -> ('27101', '27101')
    """
    if not raw_loc:
        return ('', '')
    
    clean = raw_loc.strip()
    lower = clean.lower()
    
    # 1. Pure 5-digit US ZIP code
    zip_match = re.search(r'\b(\d{5})\b', clean)
    if re.fullmatch(r'\d{5}', clean):
        return (clean, clean)
        
    # 2. Check Neighborhood / Area Map first (e.g. 'Logan Circle')
    clean_area = re.sub(r'[^a-z\s]', '', lower).strip()
    if clean_area in NEIGHBORHOOD_MAP:
        c, s = NEIGHBORHOOD_MAP[clean_area]
        slug = f"{c.lower().replace(' ', '-')}-{s.lower()}"
        return (f"{c}, {s}", slug)
        
    # 3. Check Major Cities map (e.g. 'Winston Salem' -> NC)
    if clean_area in MAJOR_CITIES:
        c, s = MAJOR_CITIES[clean_area]
        slug = f"{c.lower().replace(' ', '-')}-{s.lower()}"
        return (f"{c}, {s}", slug)

    # 4. Check if street address format is present (e.g. '1515 Q St NW, Washington, DC')
    # If commas exist, often the street is in the first part and city/state in the rest
    if ',' in clean:
        parts = [p.strip() for p in clean.split(',') if p.strip()]
        if len(parts) >= 2:
            # Check if last part or second part has state code
            last_part = parts[-1]
            last_clean = re.sub(r'\b\d{5}\b', '', last_part).strip() # strip zip if present
            
            # Is last part a state code? (e.g. 'DC' or 'MD' or 'NC')
            state_match = None
            if last_clean.upper() in STATE_CODES:
                state_match = last_clean.upper()
                city_part = parts[-2]
            else:
                # Check if last part contains city and state like 'Washington DC' or 'Rockville MD'
                words = last_clean.split()
                if words and words[-1].upper() in STATE_CODES:
                    state_match = words[-1].upper()
                    city_part = ' '.join(words[:-1])
                elif last_clean.lower() in US_STATES:
                    state_match = US_STATES[last_clean.lower()]
                    city_part = parts[-2]
                else:
                    city_part = parts[-1]
                    
            if state_match:
                # Clean city part from any remaining street numbers
                city_clean = re.sub(r'^(?:unit|apt|ste|#)\s*\w+\s*', '', city_part, flags=re.I).strip()
                city_clean = re.sub(r'^\d+\s+', '', city_clean).strip()
                if city_clean:
                    city_slug = re.sub(r'[^a-z0-9]+', '-', city_clean.lower()).strip('-')
                    return (f"{city_clean.title()}, {state_match}", f"{city_slug}-{state_match.lower()}")

    # 5. Look for State name or State code at the end of the string
    # e.g. 'Winston Salem NC' or 'Coral Gables Florida'
    for full_name, code in US_STATES.items():
        pattern = rf'\b{full_name}\b'
        if re.search(pattern, lower):
            city_portion = re.sub(pattern, '', lower).strip()
            city_clean = re.sub(r'[^a-zA-Z\s]', ' ', city_portion).strip()
            # If city_clean has street parts, extract city
            city_words = city_clean.split()
            if city_words:
                c_title = ' '.join(city_words).title()
                slug = f"{'-'.join(city_words).lower()}-{code.lower()}"
                return (f"{c_title}, {code}", slug)
            else:
                return (full_name.title(), code.lower())

    # Look for 2-letter state code at word boundary
    words = clean.split()
    if words and words[-1].upper() in STATE_CODES:
        state_code = words[-1].upper()
        city_words = words[:-1]
        # Remove trailing zip or commas
        city_words = [w.strip(',') for w in city_words if not re.match(r'^\d{5}$', w)]
        if city_words:
            # Check if first word is street number
            if len(city_words) > 2 and re.match(r'^\d+$', city_words[0]):
                # Skip street address number
                city_words = city_words[-2:]
            c_name = ' '.join(city_words).strip()
            city_slug = re.sub(r'[^a-z0-9]+', '-', c_name.lower()).strip('-')
            return (f"{c_name.title()}, {state_code}", f"{city_slug}-{state_code.lower()}")

    # 6. Fallback: if single state code was provided (e.g. 'TX')
    if clean.upper() in STATE_CODES:
        return (clean.upper(), clean.lower())

    # 7. Generic fallback slug
    clean_slug = '-'.join(re.sub(r'[^a-zA-Z0-9\s]', ' ', clean).lower().split())
    return (clean, clean_slug)
