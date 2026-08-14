import asyncio
import json
import re
import time

from pydoll.browser.chromium import Chrome

#formata o cnj para se encaixar no valor esperado pelo eproc 
def normalizar_cnj(numero: str) -> str:
    valor = re.sub(r'\D', '', numero or '')
    if not valor:
        return (numero or '').strip()

    if len(valor) >= 20:
        valor = valor[:20]
        return f'{valor[:7]}-{valor[7:9]}.{valor[9:13]}.{valor[13]}.{valor[14:16]}.{valor[16:]}'

    return (numero or '').strip()


def _normalizar_texto(texto: str | None) -> str:
    return re.sub(r'\s+', ' ', (texto or '')).strip().lower()

#indicadores para detectar se o erro é de captca
def _texto_indica_captcha_pendente(texto: str | None) -> bool:
    valor = _normalizar_texto(texto)
    if not valor:
        return False

    indicadores = (
        'captcha',
        'verificação de segurança',
        'completar a verificação',
        'cloudflare',
        'turnstile',
        'challenge',
        'sua presença é necessária',
        'verifique que você é humano',
        'anti-bot',
        'confirmação de segurança',
        'robô',
        'security check',
    )
    return any(indicador in valor for indicador in indicadores)

#indicadores para decetar se o processo é privado ou sigiloso, separados por palavras chaves
def _texto_indica_processo_privado(texto: str | None) -> bool:
    valor = _normalizar_texto(texto)
    if not valor:
        return False

    indicadores = (
        'processo privado',
        'este processo é privado',
        'consulta restrita',
        'acesso restrito',
        'dados restritos',
        'sistema privado',
        'sigiloso',
        'sigilo',
        'privado',
        'chave/senha de acesso.'
    )
    return any(indicador in valor for indicador in indicadores)

#valida se o cnj inserido está no formato correto
def validar_cnj_para_envio(numero: str) -> str:
    cnj = normalizar_cnj(numero)
    if not re.fullmatch(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', cnj):
        raise ValueError(f'CNJ inválido para consulta: {numero!r}')
    return cnj


def _extrair_valor_execucao_script(resultado):
    if isinstance(resultado, dict):
        if 'result' in resultado and isinstance(resultado['result'], dict):
            if 'value' in resultado['result']:
                return resultado['result']['value']
            if 'result' in resultado['result'] and isinstance(resultado['result']['result'], dict):
                return resultado['result']['result'].get('value')
            return resultado['result']
        if 'value' in resultado:
            return resultado['value']
    return resultado

#coleta o token do captcha
async def obter_token_turnstile(tab) -> str:
    try:
        resultado = await tab.execute_script(
            """
            (() => {
                const selectors = [
                    'input[name="cf-turnstile-response"]',
                    'textarea[name="cf-turnstile-response"]',
                    '[name="cf-turnstile-response"]'
                ];

                for (const selector of selectors) {
                    const element = document.querySelector(selector);
                    if (element && element.value) {
                        return element.value;
                    }
                }

                for (const el of document.querySelectorAll('input, textarea')) {
                    const name = (el.name || '').toLowerCase();
                    if ((name.includes('turnstile') || name.includes('cf-turnstile')) && el.value) {
                        return el.value;
                    }
                }

                return '';
            })();
            """,
            return_by_value=True,
        )
        valor = _extrair_valor_execucao_script(resultado)
        return (valor or '').strip()
    except Exception:
        return ''

#aguarda o token estar disponível para enviar o formulário
async def esperar_token_turnstile(tab, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        token = await obter_token_turnstile(tab)
        if token:
            return token

        try:
            campo = await tab.find(id='txtNumProcesso', timeout=1, raise_exc=False)
            if campo is not None:
                return ''
        except Exception:
            pass

        await asyncio.sleep(1)

    return ''

#valida se a página está pronta para envio do formulário, usando as funções de validar o captcha e se o processo não é acessível
async def validar_pagina_antes_do_submit(tab) -> None:
    try:
        campo = await tab.find(id='txtNumProcesso', timeout=5, raise_exc=False)
        if campo is not None:
            return
    except Exception:
        campo = None

    try:
        titulo = await tab.title
    except Exception:
        titulo = ''

    try:
        html_da_pagina = await tab.page_source
    except Exception:
        html_da_pagina = ''

    texto_total = f'{titulo} {html_da_pagina}'

    if _texto_indica_processo_privado(texto_total):
        raise RuntimeError(
            'A página indica que o processo é privado/sigiloso; a consulta pública não está disponível para este CNJ.'
        )

    if _texto_indica_captcha_pendente(texto_total):
        raise RuntimeError(
            'Captcha ainda não foi concluído. Resolva a verificação antes de enviar o CNJ.'
        )

#prepara o script para enviar o formulário
def _script_submit_cnj(cnj: str, token_turnstile: str) -> str:
    cnj_js = json.dumps(cnj)
    token_js = json.dumps(token_turnstile)
    return f"""
        const campo = document.getElementById('txtNumProcesso');
        const form = document.getElementById('frmProcessoLista');
        const botao = document.getElementById('sbmNovo');

        if (!campo || !form || !botao) {{
            return false;
        }}

        let tokenInput = document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"], [name="cf-turnstile-response"]');
        if (!tokenInput) {{
            tokenInput = document.createElement('input');
            tokenInput.type = 'hidden';
            tokenInput.name = 'cf-turnstile-response';
            form.appendChild(tokenInput);
        }}
        tokenInput.value = {token_js};

        let infraCaptcha = document.querySelector('input[name="hdnInfraCaptcha"], [name="hdnInfraCaptcha"]');
        if (!infraCaptcha) {{
            infraCaptcha = document.createElement('input');
            infraCaptcha.type = 'hidden';
            infraCaptcha.name = 'hdnInfraCaptcha';
            form.appendChild(infraCaptcha);
        }}
        infraCaptcha.value = '1';

        let prefixo = document.querySelector('input[name="hdnInfraPrefixoCookie"], [name="hdnInfraPrefixoCookie"]');
        if (!prefixo) {{
            prefixo = document.createElement('input');
            prefixo.type = 'hidden';
            prefixo.name = 'hdnInfraPrefixoCookie';
            form.appendChild(prefixo);
        }}
        prefixo.value = 'TJSP_Eproc_';

        campo.value = {cnj_js};

        if (typeof form.onsubmit === 'function' && !form.onsubmit()) {{
            return false;
        }}

        if (typeof form.requestSubmit === 'function') {{
            form.requestSubmit(botao);
        }} else {{
            form.submit();
        }}

        return true;
    """

#resolve o captcha e envia o formulário com o cnj
async def solve_turnstile(numero_processo: str):
    browser = Chrome()

    try:
        tab = await browser.start()

        async with tab.expect_and_bypass_cloudflare_captcha(time_to_wait_captcha=15):
            await tab.go_to(
                'https://eproc-consulta.tjsp.jus.br/consulta_1g/externo_controlador.php?acao=tjsp@consulta_unificada_publica/consultar'
            )

        print('Turnstile handled, continuing...')
        await validar_pagina_antes_do_submit(tab)

        token_turnstile = await esperar_token_turnstile(tab, timeout=30.0)
        if not token_turnstile:
            raise RuntimeError(
                'Token do Cloudflare/Turnstile não foi gerado após a resolução do captcha; a página não está pronta para a consulta.'
            )

        numero_cnj = validar_cnj_para_envio(numero_processo)
        print(f'CNJ formatado: {numero_cnj}')

        campo = await tab.find(id='txtNumProcesso', timeout=20)
        if campo is None:
            raise RuntimeError('Campo de processo não encontrado na página.')

        await campo.clear()
        await campo.insert_text(numero_cnj)

        form = await tab.find(id='frmProcessoLista', timeout=20)
        if form is None:
            raise RuntimeError('Formulário de consulta não encontrado na página.')

        script_submit = _script_submit_cnj(numero_cnj, token_turnstile)
        await tab.execute_script(script_submit)

        print(f'Processo {numero_cnj} inserido e formulário enviado.')
        print('Aguardando a navegação para a página de dados...')

        await asyncio.sleep(8)
        url_atual = await tab.current_url
        print('URL atual: ', url_atual)
        print('Página mantida aberta. Pressione Ctrl+C no terminal para encerrar.')

        await asyncio.Event().wait()
    finally:
        try:
            await browser.stop()
        except Exception:
            pass


def main():
    numero_processo = input('Digite o número do processo (CNJ): ').strip()
    if not numero_processo:
        print('Número do processo não informado.')
        return

    try:
        asyncio.run(solve_turnstile(numero_processo))
    except KeyboardInterrupt:
        print('\nExecução encerrada pelo usuário.')
    except asyncio.CancelledError:
        print('\nExecução interrompida.')
    except ValueError as exc:
        print(f'Erro no CNJ: {exc}')
    except RuntimeError as exc:
        print(f'Validação de acesso: {exc}')


if __name__ == '__main__':
    main()