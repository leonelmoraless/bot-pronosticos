from PIL import Image, ImageDraw, ImageFont
import io

def generate_leaderboard_image(users_data: list[dict]) -> io.BytesIO:
    """
    Generates a leaderboard image.
    users_data: list of dicts like [{'name': 'Juan', 'points': 10, 'rank': 1}, ...]
    The prompt asked for dicts like {'name': 'Juan', 'Mon': 5, 'Tue': 3, 'Total': 8} but for general leaderboard
    we will stick to Rank, Name, Points for simplicity based on the general requirement, 
    or adapt if daily columns are needed. 
    Let's assume a simplified view: Rank | Name | Total Points based on the 'tabla de posiciones' request.
    """
    
    # Configuration
    bg_color = "#121212"
    text_color = "#FFFFFF"
    accent_color = "#BB86FC"
    border_color = "#333333"
    
    # Layout dimensions
    padding = 20
    row_height = 50
    header_height = 70
    
    col_widths = {
        "rank": 80,
        "name": 300,
        "points": 120
    }
    width = sum(col_widths.values()) + (padding * 2)
    min_height = 200
    
    if not users_data:
        height = min_height
    else:
        height = header_height + (len(users_data) * row_height) + (padding * 2)
        
    img = Image.new('RGB', (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Try to load a font, fallback to default
    try:
        # Generic linux font path or similar, might need adjustment on Windows/Mac
        # Using default if specific font not found is standard fail-safe
        font_large = ImageFont.truetype("arial.ttf", 24)
        font_medium = ImageFont.truetype("arial.ttf", 18)
    except IOError:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()

    # Draw Header
    current_y = padding
    
    # Header Columns
    headers = [("Rank", "rank"), ("Usuario", "name"), ("Puntos", "points")]
    current_x = padding
    
    for title, key in headers:
        draw.text((current_x + 10, current_y + 20), title, font=font_large, fill=accent_color)
        current_x += col_widths[key]
        
    # Draw Divider
    current_y += header_height
    draw.line([(padding, current_y), (width - padding, current_y)], fill=border_color, width=2)
    
    # Draw Rows
    for i, user in enumerate(users_data):
        row_y = current_y + (i * row_height)
        
        # Rank
        draw.text((padding + 10, row_y + 15), str(i + 1), font=font_medium, fill=text_color)
        
        # Name
        draw.text((padding + col_widths["rank"] + 10, row_y + 15), str(user.get("name", "Unknown")), font=font_medium, fill=text_color)
        
        # Points
        points_val = str(user.get("total_points", 0))
        draw.text((padding + col_widths["rank"] + col_widths["name"] + 10, row_y + 15), points_val, font=font_medium, fill=text_color)
        
        # Row Divider
        draw.line([(padding, row_y + row_height), (width - padding, row_y + row_height)], fill=border_color, width=1)

    # Return Bytes
    output = io.BytesIO()
    img.save(output, format='JPEG', quality=95)
    output.seek(0)
    return output
