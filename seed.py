import asyncio
from app.database import AsyncSessionLocal
from app.models import Match, GameConfig, MatchStatus
from datetime import datetime, timedelta

async def seed_data():
    async with AsyncSessionLocal() as session:
        # 1. Configuración del Juego
        print("Creando configuración...")
        configs = [
            GameConfig(key="points_prime", value="5"),
            GameConfig(key="points_repechaje", value="3")
        ]
        
        for conf in configs:
            existing = await session.get(GameConfig, conf.key)
            if not existing:
                session.add(conf)
        
        # 2. Crear un Partido de prueba
        print("Creando partido de prueba...")
        # Partido para mañana
        match_date = datetime.utcnow() + timedelta(days=1)
        
        existing_match = await session.get(Match, 1)
        if not existing_match:
            match = Match(
                home_team="Real Madrid", 
                away_team="Barcelona", 
                match_date=match_date,
                status=MatchStatus.PENDING
            )
            session.add(match)
            print(f"Partido creado: Real Madrid vs Barcelona (ID: 1)")
        else:
            print("El partido ID 1 ya existe.")

        await session.commit()
        print("✅ Datos de prueba insertados exitosamente.")

if __name__ == "__main__":
    asyncio.run(seed_data())
