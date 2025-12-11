from app.models import PredictionType

def calculate_score(pred_home: int, pred_away: int, real_home: int, real_away: int, config_dict: dict) -> tuple[int, PredictionType]:
    """
    Calculates points based on prediction vs real result.
    Returns (points, PredictionType).
    """
    points_prime = int(config_dict.get("points_prime", 5))
    points_repechaje = int(config_dict.get("points_repechaje", 3))

    # EXACT MATCH (PRIME)
    if pred_home == real_home and pred_away == real_away:
        return points_prime, PredictionType.PRIME

    # CHECK FOR RESULT MATCH (REPECHAJE)
    # Case 1: Real Home Win
    if real_home > real_away:
        if pred_home > pred_away:
            return points_repechaje, PredictionType.REPECHAJE
    
    # Case 2: Real Away Win
    elif real_away > real_home:
        if pred_away > pred_home:
            return points_repechaje, PredictionType.REPECHAJE
            
    # Case 3: Real Draw
    else: # real_home == real_away
        if pred_home == pred_away:
            return points_repechaje, PredictionType.REPECHAJE

    # FAIL
    return 0, PredictionType.FAIL
