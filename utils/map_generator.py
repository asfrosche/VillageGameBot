# utils/map_generator.py
import folium
from folium.plugins import HeatMap
from io import BytesIO

def create_location_map(locations_data):
    """Create a map with markers for each location"""
    # Create Folium map with OpenStreetMap tiles
    m = folium.Map(tiles='OpenStreetMap')
    
    # Add markers with user info
    for user_id, loc in locations_data.items():
        popup = folium.Popup(f"<b>{loc['username']}</b><br>{loc['city']}, {loc['country']}", max_width=250)
        folium.CircleMarker(
            location=[loc['lat'], loc['lon']],
            radius=6,
            popup=popup,
            color='#7289da',
            fill=True,
            fill_color='#7289da'
        ).add_to(m)

    # Return the map object
    return m

def create_heatmap(locations_data):
    """Create a heatmap of user locations"""
    # Create base map with OpenStreetMap tiles
    m = folium.Map(tiles='OpenStreetMap')

    # Prepare data for heatmap (latitude, longitude, weight)
    heatmap_data = []
    for user_id, loc in locations_data.items():
        # Add location to heatmap data
        heatmap_data.append([loc['lat'], loc['lon']])

    # Add HeatMap layer to the map
    if heatmap_data:
        HeatMap(heatmap_data, radius=10, blur=15).add_to(m)

    # Return the map object
    return m

def map_to_bytes(map_obj):
    """Convert a folium map to bytes for sending as a file"""
    map_buffer = BytesIO()
    map_obj.save(map_buffer, close_file=False)
    map_buffer.seek(0)
    return map_buffer
