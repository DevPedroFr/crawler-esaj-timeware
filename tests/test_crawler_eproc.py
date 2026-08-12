import asyncio

import pytest

from crawler_eproc import (
    _script_submit_cnj,
    _texto_indica_captcha_pendente,
    _texto_indica_processo_privado,
    normalizar_cnj,
    validar_cnj_para_envio,
    validar_pagina_antes_do_submit,
)


def test_normalizar_cnj():
    raw = "10336158920228260002"
    assert normalizar_cnj(raw) == "1033615-89.2022.8.26.0002"

    raw_extra = "103361589202282600020"
    assert normalizar_cnj(raw_extra) == "1033615-89.2022.8.26.0002"


def test_validar_cnj_para_envio():
    assert validar_cnj_para_envio("1033615-89.2022.8.26.0002") == "1033615-89.2022.8.26.0002"


def test_captcha_e_privado_detectados():
    assert _texto_indica_captcha_pendente("Verificação de segurança Cloudflare") is True
    assert _texto_indica_processo_privado("Este processo é privado") is True
    assert _texto_indica_processo_privado("Consulta de processo") is False


def test_validar_cnj_rejeita_formato_invalido():
    with pytest.raises(ValueError):
        validar_cnj_para_envio("123")


def test_script_submit_cnj_usa_literal_em_vez_de_undefined():
    script = _script_submit_cnj("1033615-89.2022.8.26.0002", "token-abc")
    assert "campo.value = \"1033615-89.2022.8.26.0002\";" in script
    assert "tokenInput.value = \"token-abc\";" in script
    assert "arguments[0]" not in script


def test_validar_pagina_antes_do_submit_nao_acha_falso_positivo_de_captcha():
    class FakeTab:
        title = "Consulta processual"
        page_source = "<html><body>Cloudflare Turnstile challenge script</body></html>"

        async def find(self, **kwargs):
            return object()

    asyncio.run(validar_pagina_antes_do_submit(FakeTab()))
