import asyncio
from app.database import AsyncSessionLocal
from app.models import User
from sqlalchemy import select

async def make_admin(phone_number: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == phone_number))
        user = result.scalar_one_or_none()
        
        if user:
            user.is_admin = True
            await session.commit()
            print(f"✅ Usuario {phone_number} es ahora ADMINISTRADOR.")
        else:
            print(f"❌ Usuario {phone_number} no encontrado. Ejecuta primero un comando con él.")

if __name__ == "__main__":
    # Usamos el número que usaste en la prueba anterior
    asyncio.run(make_admin(51999999999))
