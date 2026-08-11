import requests
from pathlib import Path

url = 'https://esaj.tjsp.jus.br/cpopg/show.do?processo.codigo=02002ATD60000&processo.foro=2&processo.numero=1033615-89.2022.8.26.0002'
resp = requests.get(url, timeout=30)
print(resp.status_code)
Path('debug_page.html').write_text(resp.text, encoding='utf-8')
text = resp.text
for marker in ['Partes do processo','Movimentações','Petições diversas']:
    idx = text.find(marker)
    print(marker, idx)
    if idx != -1:
        print(text[idx-300:idx+4000])
        print('---')
