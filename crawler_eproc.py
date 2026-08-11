import asyncio

from pydoll.browser.chromium import Chrome

async def solve_turnstile():
    async with Chrome() as browser:
        tab = await browser.start()

        # Waits for the Turnstile widget, performs a realistic click,
        # and continues once it settles.
        async with tab.expect_and_bypass_cloudflare_captcha():
            await tab.go_to('https://eproc-consulta.tjsp.jus.br/consulta_1g/externo_controlador.php?acao=tjsp@consulta_unificada_publica/consultar')

        print('Turnstile handled, continuing...')

asyncio.run(solve_turnstile())