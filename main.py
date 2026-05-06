import asyncio
import base64
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright

app = FastAPI()


class CarouselRequest(BaseModel):
    html: str
    slides: int
    slide_width: int = 420
    slide_height: int = 525


class SlideImage(BaseModel):
    slide: int
    image: str  # base64 PNG


class CarouselResponse(BaseModel):
    slides: list[SlideImage]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/screenshot", response_model=CarouselResponse)
async def screenshot(request: CarouselRequest):
    if request.slides < 1 or request.slides > 20:
        raise HTTPException(status_code=400, detail="slides must be between 1 and 20")

    scale = 1080 / request.slide_width
    results = []

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

            png_bytes = await page.screenshot(
                clip={
                    "x": 0,
                    "y": 0,
                    "width": request.slide_width,
                    "height": request.slide_height,
                }
            )

            b64 = base64.b64encode(png_bytes).decode()
            results.append(SlideImage(slide=i + 1, image=f"data:image/png;base64,{b64}"))

        await browser.close()

    return CarouselResponse(slides=results)
