import json, os

HERE = os.path.dirname(os.path.abspath(__file__))

# Team ratings from worldcupsimulator.py TEAM_METRICS (using ELO as FIFA rating)
TEAM_RATINGS = {
    "Mexico": 1809, "South Africa": 1300, "Korea Republic": 1529, "Czechia": 1529,
    "Canada": 1628, "Bosnia and Herzegovina": 1580, "USA": 1820, "Paraguay": 1628,
    "Qatar": 1300, "Switzerland": 1820, "Brazil": 2127, "Morocco": 1799,
    "Haiti": 1300, "Scotland": 1679, "Australia": 1332, "Türkiye": 1758,
    "Germany": 2049, "Curaçao": 1300, "Netherlands": 2011, "Japan": 1758,
    "Côte d'Ivoire": 1660, "Ecuador": 1758, "Sweden": 1701, "Tunisia": 1373,
    "Spain": 2200, "Cabo Verde": 1300, "Belgium": 1956, "Egypt": 1602,
    "Saudi Arabia": 1300, "Uruguay": 1831, "IR Iran": 1471, "New Zealand": 1300,
    "France": 2191, "Senegal": 1727, "Iraq": 1300, "Norway": 1916,
    "Argentina": 2101, "Algeria": 1602, "Austria": 1758, "Jordan": 1300,
    "Congo DR": 1430, "Portugal": 2094, "Uzbekistan": 1300, "Colombia": 1857,
    "Croatia": 1809, "England": 2148, "Ghana": 1628, "Panama": 1300,
}

# Read current matches.json
with open(os.path.join(HERE, '..', 'data', 'matches.json'), 'r', encoding='utf-8') as f:
    data = json.load(f)

# Add ratings to all upcoming matches
for match in data.get('upcoming', []):
    for side in ['home', 'away']:
        team_name = match[side].get('name')
        if team_name and 'rating' not in match[side]:
            match[side]['rating'] = TEAM_RATINGS.get(team_name, 1300)

# Write back
with open(os.path.join(HERE, '..', 'data', 'matches.json'), 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Updated {len(data['upcoming'])} upcoming matches with ratings")