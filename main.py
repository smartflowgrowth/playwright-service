import asyncio
import os
import time
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright

# Diretório onde os PNGs serão salvos temporariamente
IMAGES_DIR = Path("/app/images")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# URL pública base (configurada via variável de ambiente no Railway)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Tempo de vida dos arquivos antes da limpeza (em segundos)
FILE_TTL_SECONDS = 3600  # 1 hora

app = FastAPI()

# Servir os PNGs gerados em https://seu-dominio/images/<arquivo>.png
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")


class CarouselRequest(BaseModel):
    html: str
    slides: int
    slide_width: int = 420
    slide_height: int = 525


class SlideImage(BaseModel):
    slide: int
    url: str


class CarouselResponse(BaseModel):
    slides: list[SlideImage]


async def cleanup_old_files():
    """Remove arquivos PNG mais antigos que FILE_TTL_SECONDS."""
    while True:
        try:
            now = time.time()
            for file in IMAGES_DIR.glob("*.png"):
                try:
                    if now - file.stat().st_mtime > FILE_TTL_SECONDS:
                        file.unlink()
                except FileNotFoundError:
                    pass
        except Exception as e:
            print(f"[cleanup] erro: {e}")
        await asyncio.sleep(600)  # roda a cada 10 minutos


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_files())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/screenshot", response_model=CarouselResponse)
async def screenshot(request: CarouselRequest):
    if request.slides < 1 or request.slides > 20:
        raise HTTPException(status_code=400, detail="slides must be between 1 and 20")

    scale = 1080 / request.slide_width
    results = []

    # Identificador único pra esse lote de slides
    batch_id = uuid.uuid4().hex[:8]

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(
            viewport={"width": request.slide_width, "height": request.slide_height},
            device_scale_factor=scale,
        )
        await page.set_content(request.html, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        await page.evaluate("""() => {
            document.querySelectorAll('.ig-header,.ig-dots,.ig-actions,.ig-caption')
                .forEach(el => el.style.display = 'none');
            const frame = document.querySelector('.ig-frame');
            if (frame) {
                frame.style.cssText = 'width:420px;height:525px;max-width:none;border-radius:0;box-shadow:none;overflow:hidden;margin:0;';
            }
            const viewport = document.querySelector('.carousel-viewport');
            if (viewport) {
                viewport.style.cssText = 'width:420px;height:525px;aspect-ratio:unset;overflow:hidden;cursor:default;';
            }
            document.body.style.cssText = 'padding:0;margin:0;display:block;overflow:hidden;';
        }""")
        await page.wait_for_timeout(500)

        for i in range(request.slides):
            await page.evaluate("""(idx) => {
                const track = document.querySelector('.carousel-track');
                if (track) {
                    track.style.transition = 'none';
                    track.style.transform = 'translateX(' + (-idx * 420) + 'px)';
                }
            }""", i)
            await page.wait_for_timeout(400)

            filename = f"slide_{batch_id}_{i + 1}.png"
            file_path = IMAGES_DIR / filename

            await page.screenshot(
                path=str(file_path),
                clip={
                    "x": 0,
                    "y": 0,
                    "width": request.slide_width,
                    "height": request.slide_height,
                }
            )

            public_url = f"{PUBLIC_BASE_URL}/images/{filename}"
            results.append(SlideImage(slide=i + 1, url=public_url))

        await browser.close()

    return CarouselResponse(slides=results)
