# EA Sports FC 26 Player Ratings Pipeline
# This shows the expected structure for integrating FIFA ratings

FC_PLAYER_ATTRIBUTES = {
    "GK": ["diving", "handling", "kicking", "reflexes", "speed", "positioning"],
    "DEF": ["acceleration", "sprint", "positioning", "interceptions", "heading_accuracy", "standing_tackle", "sliding_tackle"],
    "MID": ["acceleration", "sprint", "positioning", "vision", "crossing", "short_pass", "long_pass", "interceptions", "heading_accuracy"],
    "FWD": ["acceleration", "sprint", "positioning", "finishing", "shot_power", "long_shots", "penalties", "vision", "volleys"],
}

# Example: Expected FC 26 player format in players.json
EXAMPLE_FC_PLAYER = {
    "id": 1,
    "firstName": "Manuel",
    "lastName": "Neuer",
    "knownName": null,
    "squadId": 5,
    "position": "GK",
    "price": 5.5,
    "status": "playing",
    "fcRating": 85,  # Overall FIFA 26 rating
    "attributes": {
        "diving": 87, "handling": 90, "kicking": 78, "reflexes": 85, "speed": 55, "positioning": 88
    }
}

# Team FIFA 26 Overall Ratings (mock based on real-world strength)
FC_TEAM_RATINGS = {
    "Mexico": 78, "South Africa": 68, "Korea Republic": 77, "Czechia": 79,
    "Canada": 76, "Bosnia and Herzegovina": 77, "USA": 81, "Paraguay": 76,
    "Qatar": 70, "Switzerland": 82, "Brazil": 86, "Morocco": 78,
    "Haiti": 62, "Scotland": 79, "Australia": 74, "Türkiye": 80,
    "Germany": 85, "Curaçao": 65, "Netherlands": 84, "Japan": 79,
    "Côte d'Ivoire": 77, "Ecuador": 80, "Sweden": 81, "Tunisia": 75,
    "Spain": 88, "Cabo Verde": 65, "Belgium": 84, "Egypt": 76,
    "Saudi Arabia": 70, "Uruguay": 82, "IR Iran": 74, "New Zealand": 67,
    "France": 89, "Senegal": 78, "Iraq": 68, "Norway": 81,
    "Argentina": 90, "Algeria": 76, "Austria": 80, "Jordan": 68,
    "Congo DR": 72, "Portugal": 85, "Uzbekistan": 69, "Colombia": 80,
    "Croatia": 82, "England": 88, "Ghana": 76, "Panama": 70,
}