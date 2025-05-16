from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
DB = Path(__file__).with_name("estoque.db")

# ───────────── BANCO ─────────────
def init_db():
    with sqlite3.connect(DB) as c:
        # motos
        c.execute("""
            CREATE TABLE IF NOT EXISTS motos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                modelo TEXT, chassi TEXT, placa TEXT, cor TEXT, ano TEXT,
                origem TEXT, preco_aquisicao REAL, preco_venda REAL,
                vendido INTEGER DEFAULT 0
            )""")
        # custos por moto
        c.execute("""
            CREATE TABLE IF NOT EXISTS moto_custos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                moto_id INTEGER NOT NULL,
                descricao TEXT, valor REAL,
                FOREIGN KEY(moto_id) REFERENCES motos(id) ON DELETE CASCADE
            )""")
        # leads
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT, telefone TEXT, cpf TEXT, data_nasc TEXT,
                produto_id INTEGER, temperatura TEXT, observacoes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
        # vendas
        c.execute("""
            CREATE TABLE IF NOT EXISTS vendas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT, telefone TEXT, cpf TEXT, data_nasc TEXT,
                endereco TEXT, bairro TEXT, cidade TEXT, cep TEXT, email TEXT,
                produto_id INTEGER, data_venda TEXT, lead_id INTEGER,
                condicao_pagamento TEXT
            )""")
        # custos por venda
        c.execute("""
            CREATE TABLE IF NOT EXISTS venda_custos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venda_id INTEGER NOT NULL,
                descricao TEXT, valor REAL,
                FOREIGN KEY(venda_id) REFERENCES vendas(id) ON DELETE CASCADE
            )""")
        # financeiro: custos gerais
        c.execute("""
            CREATE TABLE IF NOT EXISTS financeiro_custos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ano INTEGER, mes INTEGER,
                descricao TEXT, valor REAL
            )""")

# ──────────── HELPERS ────────────
def query(sql, params=(), one=False):
    with sqlite3.connect(DB) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(sql, params)
        rows = cur.fetchall()
    return rows[0] if one else rows

def execute(sql, params=()):
    with sqlite3.connect(DB) as c:
        c.execute(sql, params)

def custo_total_aquisicao(v):
    base = v["preco_aquisicao"]
    extras = sum(r["valor"] for r in query(
        "SELECT valor FROM moto_custos WHERE moto_id=?", (v["produto_id"],)))
    return base + extras

def custo_total_venda(v):
    aq = custo_total_aquisicao(v)
    cv = sum(r["valor"] for r in query(
        "SELECT valor FROM venda_custos WHERE venda_id=?", (v["id"],)))
    return aq + cv

def _motos_dropdown():
    return query("""
        SELECT id,
               modelo || ' – ' ||
               COALESCE(NULLIF(placa,''), NULLIF(chassi,''), 'sem id') AS label
        FROM motos WHERE vendido=0 ORDER BY modelo
    """)

# ──────────── ROTA: FINANCEIRO ────────────
def financeiro_periodos():
    anos_v = [int(r[0]) for r in query(
        "SELECT DISTINCT strftime('%Y',data_venda) FROM vendas")]
    anos_c = [r["ano"] for r in query(
        "SELECT DISTINCT ano FROM financeiro_custos")]
    return sorted(set(anos_v + anos_c), reverse=True) or [datetime.now().year]

@app.route("/financeiro")
def financeiro():
    hoje = datetime.now()
    return render_template("financeiro.html",
                           anos=financeiro_periodos(),
                           ano_atual=hoje.year,
                           mes_atual=hoje.month)

@app.route("/financeiro/<int:ano>/<int:mes>")
def financeiro_dados(ano, mes):
    ini = f"{ano}-{mes:02d}-01"
    fim = f"{ano}-{mes:02d}-31"
    vendas = query("""
        SELECT v.id, v.nome, v.data_venda, v.produto_id,
               m.modelo, m.preco_venda, m.preco_aquisicao
        FROM vendas v
        JOIN motos m ON m.id=v.produto_id
        WHERE v.data_venda BETWEEN ? AND ?
    """, (ini, fim))

    total_vendas = sum(v["preco_venda"] for v in vendas)
    # soma custo aquisição + custos de venda
    custo_total  = sum(custo_total_venda(v) for v in vendas)
    lucro_bruto  = total_vendas - custo_total

    custos_mens  = sum(r["valor"] for r in query(
        "SELECT valor FROM financeiro_custos WHERE ano=? AND mes=?", (ano, mes)))
    # comissão de 10% sobre lucro bruto, mínimo R$100 por venda
    comissao = 0
    for v in vendas:
        lucro = (v["preco_venda"] - custo_total_venda(v))
        comissao += max(0.10 * lucro, 100.0)

    lucro_liq    = lucro_bruto - comissao - custos_mens

    detalhes = []
    custos_map = {}
    for v in vendas:
        ct = custo_total_venda(v)
        detalhes.append({**dict(v), "custo_total": ct})
        custos_map[v["id"]] = [dict(r) for r in query(
            "SELECT descricao,valor FROM venda_custos WHERE venda_id=?", (v["id"],))]

    return jsonify({
        "total_vendas":    total_vendas,
        "custo_total":     custo_total,
        "lucro_bruto":     lucro_bruto,
        "custos_mensais":  custos_mens,
        "comissao":        comissao,
        "lucro_liquido":   lucro_liq,
        "detalhes_vendas": detalhes,
        "custos_venda":    custos_map
    })

@app.route("/financeiro/custos/<int:ano>/<int:mes>")
def financeiro_custos_page(ano, mes):
    custos = query(
        "SELECT * FROM financeiro_custos WHERE ano=? AND mes=?", (ano, mes))
    return render_template("financeiro_custos.html",
                           ano=ano, mes=mes, custos=custos)

@app.route("/financeiro/custos", methods=["POST"])
def financeiro_gravar_custos():
    ano, mes = int(request.form["ano"]), int(request.form["mes"])
    execute("DELETE FROM financeiro_custos WHERE ano=? AND mes=?", (ano, mes))
    for desc, val in zip(request.form.getlist("custo_desc"),
                         request.form.getlist("custo_valor")):
        if val:
            execute("""INSERT INTO financeiro_custos
                       (ano,mes,descricao,valor) VALUES(?,?,?,?)""",
                    (ano, mes, desc, float(val)))
    return redirect(url_for("financeiro"))

# ──────────── ROTA: HOME ────────────
@app.route("/")
def index():
    return render_template("index.html")

# ──────────── ROTA: ESTOQUE ────────────
@app.route("/estoque")
def estoque():
    motos = query("SELECT * FROM motos WHERE vendido=0 ORDER BY id DESC")
    total      = len(motos)
    consignada = sum(1 for m in motos if m["origem"] == "Consignada")
    propria    = sum(1 for m in motos if m["origem"] == "Propria")
    fornecedor = sum(1 for m in motos if m["origem"] == "Fornecedor")
    return render_template("estoque.html",
                           motos=motos,
                           total=total,
                           consignada=consignada,
                           propria=propria,
                           fornecedor=fornecedor)

@app.route("/estoque/origem/<origem>")
def estoque_por_origem(origem):
    origem_map = {
        "consignadas": "Consignada",
        "proprias":    "Propria",
        "fornecedor":  "Fornecedor"
    }
    o = origem_map.get(origem.lower())
    if not o:
        return redirect(url_for("estoque"))
    motos = query(
        "SELECT * FROM motos WHERE vendido=0 AND origem=? ORDER BY id DESC", (o,))
    return render_template("estoque_origem.html", motos=motos, titulo=o)

@app.route("/estoque/novo", methods=["GET","POST"])
@app.route("/estoque/editar/<int:i>", methods=["GET","POST"])
def estoque_form(i=None):
    edit = i is not None
    moto = query("SELECT * FROM motos WHERE id=?", (i,), one=True) if edit else {}
    custos = query("SELECT * FROM moto_custos WHERE moto_id=?", (i,)) if edit else []
    if request.method == "POST":
        d = {k: request.form.get(k) or None for k in (
            "modelo","chassi","placa","cor","ano","origem",
            "preco_aquisicao","preco_venda")}
        if not (d["chassi"] or d["placa"]):
            return render_template("estoque_form.html",
                                   editar=edit, moto=d, custos=custos,
                                   erro="Preencha chassi ou placa.")
        if edit:
            execute("""UPDATE motos SET
                         modelo=:modelo,chassi=:chassi,placa=:placa,cor=:cor,
                         ano=:ano,origem=:origem,
                         preco_aquisicao=:preco_aquisicao,
                         preco_venda=:preco_venda
                       WHERE id=:id""", {**d, "id": i})
            moto_id = i
        else:
            with sqlite3.connect(DB) as c:
                cur = c.execute("""INSERT INTO motos(
                             modelo,chassi,placa,cor,ano,origem,
                             preco_aquisicao,preco_venda
                           ) VALUES (
                             :modelo,:chassi,:placa,:cor,:ano,:origem,
                             :preco_aquisicao,:preco_venda
                           )""", d)
                moto_id = cur.lastrowid
        execute("DELETE FROM moto_custos WHERE moto_id=?", (moto_id,))
        for desc, val in zip(request.form.getlist("custo_desc"),
                             request.form.getlist("custo_valor")):
            if val:
                execute("""INSERT INTO moto_custos
                           (moto_id,descricao,valor) VALUES(?,?,?)""",
                        (moto_id, desc, float(val)))
        return redirect(url_for("estoque"))
    return render_template("estoque_form.html",
                           editar=edit, moto=moto, custos=custos, erro=None)

@app.route("/estoque/excluir/<int:i>", methods=["POST"])
def estoque_excluir(i):
    execute("DELETE FROM motos WHERE id=?", (i,))
    return redirect(url_for("estoque"))

# ──────────── ROTA: LEADS ────────────
@app.route("/vendas/leads")
def leads():
    lista = query("""
        SELECT l.id,
               l.created_at,
               l.nome,
               l.telefone,
               l.cpf,
               l.data_nasc,
               l.temperatura,
               m.modelo
        FROM leads l
        LEFT JOIN motos m ON m.id = l.produto_id
        ORDER BY l.created_at DESC
    """)
    return render_template("leads.html", leads=lista)

@app.route("/vendas/leads/novo", methods=["GET","POST"])
@app.route("/vendas/leads/editar/<int:i>", methods=["GET","POST"])
def leads_form(i=None):
    edit = i is not None
    lead = query("SELECT * FROM leads WHERE id=?", (i,), one=True) if edit else {}
    motos_dd = _motos_dropdown()
    if request.method == "POST":
        d = {k: request.form.get(k) or None for k in (
            "nome","telefone","cpf","data_nasc","produto_id",
            "temperatura","observacoes")}
        if not d["nome"]:
            return render_template("leads_form.html", edit=edit, lead=d,
                                   motos=motos_dd, erro="Nome obrigatório.")
        if edit:
            execute("""UPDATE leads SET
                         nome=:nome,telefone=:telefone,cpf=:cpf,
                         data_nasc=:data_nasc,produto_id=:produto_id,
                         temperatura=:temperatura,
                         observacoes=:observacoes
                       WHERE id=:id""", {**d, "id": i})
        else:
            with sqlite3.connect(DB) as c:
                c.execute("""INSERT INTO leads(
                             nome,telefone,cpf,data_nasc,produto_id,
                             temperatura,observacoes
                           ) VALUES (
                             :nome,:telefone,:cpf,:data_nasc,:produto_id,
                             :temperatura,:observacoes
                           )""", d)
        return redirect(url_for("leads"))
    return render_template("leads_form.html", edit=edit, lead=lead,
                           motos=motos_dd, erro=None)

@app.route("/vendas/leads/excluir/<int:i>", methods=["POST"])
def leads_excluir(i):
    execute("DELETE FROM leads WHERE id=?", (i,))
    return redirect(url_for("leads"))

# ──────────── ROTA: VENDAS ────────────
@app.route("/vendas")
def vendas_home():
    lista = query("""
        SELECT v.id,v.data_venda,v.nome,m.modelo,v.cidade,v.telefone
        FROM vendas v
        LEFT JOIN motos m ON m.id=v.produto_id
        ORDER BY v.data_venda DESC
    """)
    return render_template("vendas.html", vendas=lista)

@app.route("/vendas/novo", methods=["GET","POST"])
def vendas_novo():
    if request.method == "POST":
        return _salvar_venda(editar=False)
    return render_template("vendas_form.html",
                           edit=False, venda=None,
                           lead=None, motos=_motos_dropdown(), cv=[])

@app.route("/vendas/editar/<int:vid>", methods=["GET","POST"])
def vendas_editar(vid):
    venda = query("SELECT * FROM vendas WHERE id=?", (vid,), one=True)
    if not venda:
        return redirect( url_for("vendas_home") )
    if request.method == "POST":
        return _salvar_venda(editar=True, venda_id=vid, venda_original=venda)
    custos_v = query(
        "SELECT * FROM venda_custos WHERE venda_id=?", (vid,))
    return render_template("vendas_form.html",
                           edit=True, venda=venda,
                           lead=None, motos=_motos_dropdown(), cv=custos_v)

@app.route("/vendas/leads/gerar_venda/<int:lid>", methods=["GET","POST"])
def gerar_venda(lid):
    lead = query("SELECT * FROM leads WHERE id=?", (lid,), one=True)
    if request.method == "POST":
        return _salvar_venda(editar=False, lead_id=lid)
    return render_template("vendas_form.html",
                           edit=False, venda=None,
                           lead=lead, motos=_motos_dropdown(), cv=[])

def _salvar_venda(editar, venda_id=None, lead_id=None, venda_original=None):
    campos = ("nome","telefone","cpf","data_nasc","endereco","bairro","cidade",
              "cep","email","produto_id","condicao_pagamento")
    d = {k: request.form.get(k) or None for k in campos}
    d["lead_id"]    = lead_id
    d["data_venda"] = datetime.now().strftime("%Y-%m-%d")

    if editar:
        d["id"] = venda_id
        execute("""UPDATE vendas SET
                     nome=:nome,telefone=:telefone,cpf=:cpf,data_nasc=:data_nasc,
                     endereco=:endereco,bairro=:bairro,cidade=:cidade,
                     cep=:cep,email=:email,produto_id=:produto_id,
                     condicao_pagamento=:condicao_pagamento
                   WHERE id=:id""", d)
        if venda_original and venda_original["produto_id"] != int(d["produto_id"]):
            execute("UPDATE motos SET vendido=0 WHERE id=?",
                    (venda_original["produto_id"],))
    else:
        with sqlite3.connect(DB) as c:
            cur = c.execute("""INSERT INTO vendas(
                         nome,telefone,cpf,data_nasc,endereco,bairro,cidade,cep,
                         email,produto_id,data_venda,lead_id,condicao_pagamento
                       ) VALUES (
                         :nome,:telefone,:cpf,:data_nasc,:endereco,
                         :bairro,:cidade,:cep,:email,:produto_id,
                         :data_venda,:lead_id,:condicao_pagamento
                       )""", d)
            venda_id = cur.lastrowid
            c.execute("UPDATE motos SET vendido=1 WHERE id=?",
                      (d["produto_id"],))

    execute("DELETE FROM venda_custos WHERE venda_id=?", (venda_id,))
    for desc, val in zip(request.form.getlist("cv_desc"),
                         request.form.getlist("cv_valor")):
        if val:
            execute("""INSERT INTO venda_custos(venda_id,descricao,valor)
                       VALUES(?,?,?)""", (venda_id, desc, float(val)))
    return redirect(url_for("vendas_home"))

@app.route("/vendas/excluir/<int:vid>", methods=["POST"])
def vendas_excluir(vid):
    v = query("SELECT * FROM vendas WHERE id=?", (vid,), one=True)
    execute("UPDATE motos SET vendido=0 WHERE id=?", (v["produto_id"],))
    execute("DELETE FROM vendas WHERE id=?", (vid,))
    return redirect(url_for("vendas_home"))

# ──────────── ROTA: CUSTOS POR VENDA ────────────
@app.route("/vendas/<int:vid>/custos", methods=["GET","POST"])
def venda_custos(vid):
    venda = query("SELECT * FROM vendas WHERE id=?", (vid,), one=True)
    if not venda:
        return redirect(url_for("vendas_home"))
    if request.method == "POST":
        desc = request.form.get("descricao")
        val  = request.form.get("valor")
        if desc and val:
            execute("INSERT INTO venda_custos(venda_id,descricao,valor) VALUES(?,?,?)",
                    (vid, desc, float(val)))
        return redirect(url_for("venda_custos", vid=vid))
    custos = query("SELECT * FROM venda_custos WHERE venda_id=?", (vid,))
    return render_template("venda_custos.html", venda=venda, custos=custos)

# ──────────── ROTA: DOCUMENTOS ────────────
@app.route("/vendas/<int:i>/proposta")
def venda_proposta(i):
    v = query("SELECT * FROM vendas WHERE id=?", (i,), one=True)
    m = query("SELECT * FROM motos WHERE id=?", (v["produto_id"],), one=True)
    return render_template("proposta.html", v=v, m=m)

@app.route("/vendas/<int:i>/termo")
def venda_termo(i):
    v = query("SELECT * FROM vendas WHERE id=?", (i,), one=True)
    m = query("SELECT * FROM motos WHERE id=?", (v["produto_id"],), one=True)
    return render_template("termo.html", v=v, m=m)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
