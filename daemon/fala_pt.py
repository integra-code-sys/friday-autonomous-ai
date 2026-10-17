"""Texto -> fala natural em pt-BR: números, dinheiro, porcentagem, horas, datas, ordinais, abreviações e símbolos por extenso.

Os modelos de voz neurais (Pocket TTS) não sabem ler algarismos ("1234" sai como ruído), então tudo vira palavra antes.
Usado pelo daemon (_humanize) e pelo servidor de voz (tts_pocket.py). Só depende de num2words.
"""
import re

try:
    from num2words import num2words as _n2w
except Exception:                      # sem num2words: deixa os números como estão (a voz Piper lê algarismos)
    _n2w = None

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
ABREV = [(r"\bSra\.", "senhora"), (r"\bSr\.", "senhor"), (r"\bDra\.", "doutora"), (r"\bDr\.", "doutor"), (r"\bProf\.", "professor"),
         (r"\bn(?:[º°]|o\.)\s*(?=\d)", "número "), (r"\bart\.\s*(?=\d)", "artigo "), (r"\bcap\.\s*(?=\d)", "capítulo "),
         (r"\bp[áa]g\.\s*(?=\d)", "página "), (r"\bvol\.\s*(?=\d)", "volume "), (r"\bfls?\.\s*(?=\d)", "folha "),
         (r"\bLtda\.?", "limitada"), (r"\bCia\.?", "companhia"), (r"\bS\.A\.", "ésse a"), (r"\betc\.?", "etcétera"), (r"\bex\.:?", "por exemplo"), (r"\bobs\.:?", "observação:"),
         (r"\bvs\.?\b", "versus"), (r"\bp\.\s*ex\.", "por exemplo"), (r"\bqtd\.?\b", "quantidade"), (r"\bkm/h\b", "quilômetros por hora"),
         (r"(?<=\d)\s*km\b", " quilômetros"), (r"(?<=\d)\s*kg\b", " quilos"), (r"(?<=\d)\s*ml\b", " mililitros"), (r"(?<=\d)\s*min\b", " minutos"),
         (r"(?<=\d)\s*seg\b", " segundos"), (r"(?<=\d)\s*s\b", " segundos"), (r"(?<=\d)\s*h\b(?!\s*\d)", " horas"), (r"(?<=\d)\s*m\b", " metros"), (r"(?<=\d)\s*cm\b", " centímetros"), (r"(?<=\d)\s*GHz\b", " giga-hertz"),
         (r"(?<=\d)\s*MHz\b", " mega-hertz"), (r"(?<=\d)\s*W\b", " watts"), (r"(?<=\d)\s*V\b", " volts")]
SIMBOLOS = [("&", " e "), ("@", " arroba "), ("+", " mais "), ("=", " igual a "), ("§", " parágrafo "), ("°C", " graus"), ("°", " graus"),
            ("~", " cerca de "), ("×", " vezes "), ("→", ", "), ("•", ", "), ("|", ", ")]
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def _w(n, to="cardinal"):
    if _n2w is None:
        return str(n)
    s = _n2w(n, lang="pt_BR", to=to)
    return s.replace(",", "")                    # "mil, duzentos" -> "mil duzentos" (sem pausa no meio do número)


def _num_br(s):
    """'1.234,56' | '1234,5' | '1234' -> float/int no formato brasileiro."""
    s = s.strip()
    if "," in s:
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        return int(s.replace(".", ""))
    return float(s) if "." in s else int(s)


def _dinheiro(m):
    v = _num_br(m.group(1))
    reais, cent = int(v), int(round((v - int(v)) * 100))
    partes = []
    if reais:
        partes.append(_w(reais) + (" real" if reais == 1 else (" de reais" if reais % 1000000 == 0 else " reais")))
    if cent:
        partes.append(_w(cent) + (" centavo" if cent == 1 else " centavos"))
    return " e ".join(partes) or "zero reais"


def _numero(m):
    s = m.group(0)
    digitos = re.sub(r"\D", "", s)
    if len(digitos) >= 7 and "," not in s and not re.fullmatch(r"\d{1,3}(\.\d{3})+", s):     # telefone, código: em grupos
        n = len(digitos)                                  # CPF 3-3-3-2, CNPJ 2-3-3-4-2, celular c/ DDI/DDD; resto em trincas, dígito a dígito
        tam = [3, 3, 3, 2] if n == 11 and digitos[2] != "9" else [2, 3, 3, 4, 2] if n == 14 else [2, 2, 5, 4] if n == 13 else \
              [2, 5, 4] if n == 11 else [2, 4, 4] if n == 10 else [3] * (n // 3) + ([n % 3] if n % 3 else [])
        blocos, i = [], 0
        for k in tam:
            blocos.append(digitos[i:i + k]); i += k
        if n in (10, 11, 13) and tam[0] == 2:              # telefone: DDI/DDD falados como número ("cinquenta e cinco", "onze")
            blocos = [_w(int(b)) if b[0] != "0" else _digitos(b) for b in blocos[:-2]] + [_digitos(b) for b in blocos[-2:]]
            return ", ".join(blocos)
        return ", ".join(_digitos(b) for b in blocos)
    try:
        v = _num_br(s)
    except ValueError:
        return s
    if isinstance(v, float) and not v.is_integer():
        inteiro, frac = s.replace(".", "").split(",") if "," in s else s.split(".")
        return _w(int(inteiro)) + " vírgula " + (" ".join(_w(int(c)) for c in frac) if frac.startswith("0") else _w(int(frac)))
    return _w(int(v))


_DIG = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]


def _digitos(s, grupo=None):
    """'99876' -> 'nove nove oito sete seis'; grupo=n separa por vírgula a cada n (ritmo de quem dita número)."""
    d = [_DIG[int(c)] for c in s if c.isdigit()]
    if grupo:
        return ", ".join(" ".join(d[i:i + grupo]) for i in range(0, len(d), grupo))
    return " ".join(d)


def _telefone(m):
    """(11) 99876-5432 / +55 14 3456-7890 / 11998765432 -> DDD por extenso + blocos dígito a dígito, como se dita no Brasil."""
    pais, ddd, a, b = m.group("pais"), m.group("ddd"), m.group("a"), m.group("b")
    partes = []
    if pais:
        partes.append("mais " + _digitos(pais))
    if ddd:
        partes.append(_w(int(ddd)) if _n2w and ddd[0] != "0" else _digitos(ddd))     # DDD se fala como número: "onze", "catorze"
    partes.append(_digitos(a))
    partes.append(_digitos(b))
    return ", ".join(partes)


_TEL = re.compile(r"(?<![\w])(?:\+\s?(?P<pais>\d{2})\s?)?(?:\(?(?P<ddd>\d{2})\)?\s?)?(?P<a>9?\d{4})[-\s.]?(?P<b>\d{4})(?![\w])")
_LETRA = {"A": "a", "B": "bê", "C": "cê", "D": "dê", "E": "ê", "F": "éfe", "G": "gê", "H": "agá", "I": "i", "J": "jota", "K": "cá",
          "L": "éle", "M": "eme", "N": "ene", "O": "ó", "P": "pê", "Q": "quê", "R": "érre", "S": "ésse", "T": "tê", "U": "u", "V": "vê",
          "W": "dáblio", "X": "xis", "Y": "ípsilon", "Z": "zê"}


def _soletrar(s):
    """'ABC1D23' -> 'a bê cê um dê dois três' (placa, código: letra pelo nome, número dígito a dígito)."""
    return " ".join(_LETRA.get(c.upper(), c) if c.isalpha() else _DIG[int(c)] for c in s if c.isalnum())


def _blocos(*gs):
    return ", ".join(_digitos(g) for g in gs)


_ROMANO = {"I": 1, "V": 5, "X": 10}


def _romano(r):
    v = 0
    for i, c in enumerate(r):
        n = _ROMANO[c]
        v += -n if i + 1 < len(r) and _ROMANO[r[i + 1]] > n else n
    return v


_FEM = r"(?:xícara|xicara|colher|hora|dúzia|duzia|lata|caixa|garrafa|fatia|porção|porcao|pizza|parte|página|pagina)"
_FRAC = {(1, 2): None, (1, 3): "um terço", (2, 3): "dois terços", (1, 4): "um quarto", (3, 4): "três quartos"}
_VERSAO = r"(?:vers[ãa]o|version|v|python|node|kernel|android|ios|linux|release|firmware|api|build|php|java|gnome|kde|qt)"


def _previo(t):
    """formatos que as regras gerais leriam errado: documentos sem rótulo, CEP, placa, romanos, faixas, versões, frações, "5x"."""
    t = re.sub(r"(?<![\w.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?![\w])", lambda m: _blocos(*m.groups()), t)              # CPF
    t = re.sub(r"(?<![\w.])(\d{2})\.(\d{3})\.(\d{3})/(\d{4})-(\d{2})(?![\w])", lambda m: _blocos(*m.groups()), t)     # CNPJ
    t = re.sub(r"(?<![\w.\-])(\d{5})-(\d{3})(?![\w\-])", lambda m: _blocos(*m.groups()), t)                           # CEP
    t = re.sub(r"(?<![\w-])([A-Z]{3})-?(\d[A-Z0-9]\d{2})(?![\w-])", lambda m: _soletrar(m.group(1) + m.group(2)), t)  # placa (antiga e Mercosul)
    t = re.sub(r"(?i)\b(tel|cel)\.?:?\s*(?=[\d(+])", lambda m: "telefone " if m.group(1).lower() == "tel" else "celular ", t)
    t = re.sub(r"\b24\s*/\s*7\b", "vinte e quatro horas por dia, sete dias por semana", t)
    t = re.sub(r"(?<![\w/])([123])/([234])(?=\s+(\w+))", lambda m: (("meia" if re.fullmatch(_FEM, m.group(3), re.I) else "meio")
               if (int(m.group(1)), int(m.group(2))) == (1, 2) else _FRAC.get((int(m.group(1)), int(m.group(2))))) or m.group(0)
               if not re.fullmatch(r"\d+|de|do|da", m.group(3)) or (int(m.group(1)), int(m.group(2))) != (1, 2) else m.group(0), t)
    t = re.sub(r"(?i)\bR\$\s*(\d+(?:,\d+)?)\s*(mil|milh(?:ão|ões|ao|oes)|bilh(?:ão|ões|ao|oes)|bi|mi)\b",
               lambda m: m.group(1) + " " + {"bi": "bilhões", "mi": "milhões"}.get(m.group(2).lower(), m.group(2))
               + (" de reais" if not m.group(2).lower().startswith("mil") or m.group(2).lower().startswith("milh") else " reais"), t)
    # versão "3.14" / "2.5.1" = "ponto"; decimal em inglês "3.5 GB" = "vírgula" (milhar "1.234" fica para as regras gerais)
    t = re.sub(r"(?i)(\b" + _VERSAO + r"\s*)(\d+(?:\.\d+)+)\b", lambda m: m.group(1) + " ponto ".join(m.group(2).split(".")), t)
    t = re.sub(r"(?<![\w.,])(\d+(?:\.\d+){2,})(?![\w.])", lambda m: " ponto ".join(m.group(1).split(".")), t)
    t = re.sub(r"(?<![\w.,])(\d+)\.(\d{1,2}|\d{4,})(?![\w.])", r"\1,\2", t)
    t = re.sub(r"\b(\d+)[xX]\b(?!\s*\d)", lambda m: m.group(1) + (" vez" if m.group(1) == "1" else " vezes"), t)
    t = re.sub(r"(?:(?<=\s)|^)-(?=\d)", "menos ", t)                                                               # -5°C (não "Marília - 1310")
    t = re.sub(r"(?<![\w\-])(\d{1,3})\s*[-–]\s*(\d{1,3})(?![\w\-])", r"\1 a \2", t)                                  # 10-20 = dez a vinte (telefone/CEP não)
    t = re.sub(r"\b1\s+de\s+(?=" + "|".join(MESES) + r")", "primeiro de ", t)
    t = re.sub(r"(?<=[A-Za-z])-(?=\d)", " ", t)                                                                       # COVID-19
    t = re.sub(r"\b([A-Z]{2,5})\s(\d{2})(\d{2})\b(?!\s*(?:reais|%|,\d))", lambda m: m.group(1) + " " + _w(int(m.group(2))) + " "
               + (_w(int(m.group(3))) if m.group(3)[0] != "0" else "zero " + _w(int(m.group(3)))) if m.group(1) not in ("CEP", "ANO") else m.group(0), t)   # RTX 3050
    # romanos: século/capítulo/rua = cardinal; depois de nome próprio (Pedro II, João Paulo II) = ordinal
    def _rom(m):
        antes, r = m.group(1), m.group(2)
        if not re.fullmatch(r"X{0,3}(IX|IV|V?I{0,3})", r) or not r:
            return m.group(0)
        n = _romano(r)
        if re.search(r"(?i)(s[ée]culo|cap[íi]tulo|inciso|parte|volume|ato|fase|n[íi]vel|rua|avenida|av\.?|pra[çc]a|bloco|tomo|livro)\s*$", antes):
            return antes + _w(n)
        if len(r) >= 2 and re.search(r"\b[A-ZÁÉÍÓÚ][a-záéíóúâêôãõç]+\s*$", antes):        # "Banco X", "Doc X" não
            return antes + _w(n, "ordinal")
        return m.group(0) if len(r) < 2 else antes + _w(n)
    t = re.sub(r"(\S*\s?)\b([IVX]{1,6})\b(?![\w'])", _rom, t)
    t = re.sub(r"\b([B-DF-HJ-NP-TV-Z]{2,4})(\d*)\b", lambda m: m.group(0) if m.group(1) in SIGLAS or set(m.group(1)) <= set("IVX") else
               _soletrar(m.group(1)) + (" " + m.group(2) if m.group(2) else ""), t)                                    # RTX, PS5: sem vogal = soletra
    return t


_CODIGOS = [(r"\b(CPF|CNPJ|RG|CEP|PIX|ID|protocolo|c[óo]digo|senha|placa|matr[íi]cula|pedido|conta|ag[êe]ncia|identifica[çc][ãa]o|s[ée]rie|serial|chave|boleto|nota|cart[ãa]o|inscri[çc][ãa]o)\b[:\s]*((?:é|eh)\s+)?(?:n[ºo°]\.?\s*)?((?:[A-Za-z]{1,4}-?)?\d[\d.\-/]{3,})",
             lambda m: m.group(1) + " " + (m.group(2) or "") + ", ".join(_digitos(p_) if p_.isdigit() else _soletrar(p_) for p_ in re.split(r"[.\-/]|(?<=[A-Za-z])(?=\d)", m.group(3).strip(".-/")) if p_))]   # nos blocos em que se escreve; letras soletradas
# escrita de mensagem (WhatsApp) -> fala
INFORMAL = {"vc": "você", "vcs": "vocês", "tb": "também", "tbm": "também", "pq": "porque", "blz": "beleza", "msg": "mensagem",
            "msgs": "mensagens", "qdo": "quando", "qnd": "quando", "hj": "hoje", "td": "tudo", "tds": "todos", "mt": "muito", "mto": "muito",
            "mts": "muitos", "obg": "obrigado", "vlw": "valeu", "pfv": "por favor", "pf": "por favor", "cmg": "comigo", "ctg": "contigo",
            "ngm": "ninguém", "qq": "qualquer", "dps": "depois", "msm": "mesmo", "agr": "agora", "add": "adicionar", "abs": "abraços",
            "bjs": "beijos", "bj": "beijo", "sdds": "saudades", "tmj": "tamo junto", "flw": "falou", "kd": "cadê", "aki": "aqui",
            "q": "que", "n": "não", "ñ": "não", "eh": "é", "vdd": "verdade", "fds": "fim de semana", "amg": "amigo",
            "qto": "quanto", "qts": "quantos", "ql": "qual", "dnv": "de novo", "rs": "", "kkk": "", "kkkk": "", "kkkkk": "", "haha": ""}
ENDERECO = [(r"\bAv\.?(?=\s)", "avenida"), (r"\bR\.(?=\s)", "rua"), (r"\bAl\.(?=\s)", "alameda"), (r"\bTv\.(?=\s)", "travessa"),
            (r"\bEst\.(?=\s)", "estrada"), (r"\bRod\.(?=\s)", "rodovia"), (r"\bPç\.?(?=\s)", "praça"), (r"\bap(?:to?)?\.?(?=\s*\d)", "apartamento"),
            (r"\bBl\.(?=\s*\w)", "bloco"), (r"\bS/N\b", "sem número"), (r"\bAtt\.?", "atenciosamente"), (r"\bc/c\b", "com cópia")]
# siglas lidas letra a letra (como o brasileiro fala) e palavras estrangeiras comuns com pronúncia aportuguesada
SIGLAS = {"CPU": "cê pê u", "GPU": "gê pê u", "VRAM": "vê ram", "RAM": "ram", "PTZ": "pê tê zê", "PC": "pê cê", "TV": "tê vê",
          "API": "a pê i", "PDF": "pê dê éfe", "USB": "u ésse bê", "IA": "i a", "IP": "i pê", "SSD": "ésse ésse dê", "HD": "agá dê",
          "CPF": "cê pê éfe", "ID": "ái dí", "CNPJ": "cê ene pê jota", "RG": "érre gê", "CEP": "cep", "NF": "nota fiscal", "NFe": "nota fiscal eletrônica",
          "NFS-e": "nota fiscal de serviço", "OK": "ok", "Ok": "ok", "GB": "gigas", "MB": "megas", "TB": "teras", "KB": "kilobytes",
          "Wi-Fi": "uái-fái", "WiFi": "uái-fái", "wifi": "uái-fái", "VNC": "vê ene cê", "ADB": "a dê bê", "SMS": "ésse eme ésse",
          "URL": "u érre éle", "UI": "u i", "QR": "quiu-ár", "DDD": "dê dê dê", "RTSP": "érre tê ésse pê", "ONVIF": "ônvif",
          "LED": "léd", "IR": "infravermelho", "BH": "bê agá", "SP": "ésse pê", "RJ": "érre jota", "EUA": "estados unidos"}
PRONUNCIA = {"YouTube": "iutúbi", "WhatsApp": "uótsap", "Zap": "zap", "Chromium": "crômium", "Chrome": "crôme", "Google": "gúgou",
             "Gmail": "gê-mêil", "Instagram": "ínstagram", "Facebook": "fêicibuk", "Windows": "uíndous", "Linux": "línux", "GitHub": "guít-rãb",
             "Spotify": "spótifai", "Netflix": "nétiflics", "OnlyOffice": "ônli ófice", "Discord": "díscord", "Telegram": "télegram",
             "iPhone": "ai-fone", "Android": "ândroid", "Claude": "clóud", "ChatGPT": "chat gê pê tê", "Gemini": "gêmini",
             "Iann": "Ían", "Wesley": "Uésli", "William": "Uíliam", "Washington": "Uóshington", "Michael": "Máicou", "Jennifer": "Djênifer",
             "Kevin": "Kévin", "Bryan": "Bráian", "Ryan": "Ráian", "Jefferson": "Djéferson", "Wellington": "Uélington", "Jhonatan": "Jônatan",
             "Friday": "fráidei", "F.R.I.D.A.Y.": "Sexta-Feira", "Stark": "Istárk", "Tailscale": "têilsceil", "Noctalia": "noctália"}


def _email(m):
    u, d = m.group(1), m.group(2)
    fala = lambda x: x.replace(".", " ponto ").replace("_", " underline ").replace("-", " traço ")
    return f"{fala(u)} arroba {fala(d)}"


def _url(m):
    u = re.sub(r"^https?://", "", m.group(0)).rstrip("/.")
    u = re.sub(r"^www\.", "", u)
    return u.replace(".com.br", " ponto com ponto bê érre").replace(".com", " ponto com").replace(".", " ponto ").replace("/", " barra ")


def normalizar(t: str) -> str:
    if not t:
        return t
    t = _EMOJI.sub("", t)
    # e-mails e sites antes de tudo (têm pontos e números que confundem as outras regras)
    t = re.sub(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)\b", _email, t)
    t = re.sub(r"\b(?:https?://)?(?:www\.)?[\w-]+\.(?:com|com\.br|net|org|br|io|dev|app|ai|me)(?:/[\w./-]*)?", _url, t)
    # documentos/códigos e telefones: dígito a dígito (nunca "noventa e nove mil...")
    t = _previo(t)
    for pat, f in _CODIGOS:
        t = re.sub(pat, f, t, flags=re.I)
    t = _TEL.sub(_telefone, t)
    t = re.sub(r"(?<![\w@])([A-Za-zçÇ]{1,5})(?![\w@])", lambda m: INFORMAL.get(m.group(1).lower(), m.group(1))
               if m.group(1).islower() or m.group(1).lower() in ("vc", "tb", "pq", "blz", "msg", "hj") else m.group(1), t)
    for pat, rep in ENDERECO:
        t = re.sub(pat, rep, t, flags=re.I)
    for pat, rep in ABREV:
        t = re.sub(pat, rep, t, flags=re.I)
    # datas e horas (antes dos números soltos)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", lambda m: (("primeiro" if int(m.group(1)) == 1 else _w(int(m.group(1)))) + " de " + MESES[int(m.group(2)) - 1]
               + " de " + _w(int(m.group(3)) if len(m.group(3)) == 4 else 2000 + int(m.group(3)))) if 1 <= int(m.group(2)) <= 12 else m.group(0), t)
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})\b", lambda m: (("primeiro" if int(m.group(1)) == 1 else _w(int(m.group(1)))) + " de " + MESES[int(m.group(2)) - 1])
               if 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31 else m.group(0), t)
    t = re.sub(r"\b(\d{1,2})\s*(?::|h)\s*(\d{2})\b", lambda m: _w(int(m.group(1))) + (" em ponto" if m.group(2) == "00" else " e " + _w(int(m.group(2)))), t)
    t = re.sub(r"\b(\d{1,2})\s*h\b", lambda m: _w(int(m.group(1))) + (" hora" if int(m.group(1)) == 1 else " horas"), t)
    # dinheiro, porcentagem, ordinais
    t = re.sub(r"R\$\s*((?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)", _dinheiro, t)     # "R$ 2.100." no fim da frase quebrava
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*%", lambda m: _numero(re.match(r".+", m.group(1))) + " por cento", t)
    t = re.sub(r"(\d+(?:,\d+)?)\s*°\s*C?\b", lambda m: _numero(re.match(r".+", m.group(1))) + " graus", t)    # temperatura antes de ordinal
    t = re.sub(r"\b(\d+)\s*[ºo](?!\w)", lambda m: _w(int(m.group(1)), "ordinal"), t)
    t = re.sub(r"\b(\d+)\s*ª", lambda m: re.sub(r"o\b", "a", _w(int(m.group(1)), "ordinal")), t)
    # números soltos (com milhar/decimal brasileiros)
    t = re.sub(r"(?<![\w.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w])|(?<![\w.,])\d+(?:,\d+)?(?![\w])", _numero, t)
    for a, b in SIMBOLOS:
        t = t.replace(a, b)
    for k, v in sorted(PRONUNCIA.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(r"(?<![\w])" + re.escape(k) + r"(?![\w])", v, t)
    for k, v in sorted(SIGLAS.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(r"(?<![\w])" + re.escape(k) + r"(?![\w])", v, t)
    t = t.replace("…", "...").replace("—", ", ").replace("–", ", ").replace("_", " ")
    t = re.sub(r"\.{2,}", ".", t)                                # reticências geram pausas confusas/engasgo
    t = re.sub(r"[,;:\-–]{2,}", ",", t)
    t = re.sub(r"[^\w\s.,!?'\"-]", " ", t)                       # remove caracteres gráficos estranhos
    t = re.sub(r"\s+([,.!?])", r"\1", t)
    t = re.sub(r"([,.!?]){2,}", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


if __name__ == "__main__":
    import sys
    print(normalizar(" ".join(sys.argv[1:])))
