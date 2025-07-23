import os
import uuid
import psycopg2
from flask import Flask, request, jsonify
from flask_cors import CORS

# --- Configuração Inicial ---
app = Flask(__name__)

# --- Configuração de CORS Específica ---
# Define que apenas o seu subdomínio pode fazer requisições para a API.
cors = CORS(app, resources={
    r"/*": {
        "origins": "https://indica.hrtbeneficios.com.br"
    }
})

def get_db_connection():
    """Cria uma conexão com o banco de dados PostgreSQL usando a URL do ambiente."""
    conn = psycopg2.connect(os.environ.get('DATABASE_URL'))
    return conn

def init_db():
    """
    Cria as tabelas do banco de dados PostgreSQL se elas não existirem.
    A sintaxe SQL é ajustada para PostgreSQL (ex: SERIAL PRIMARY KEY).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            valor_mensalidade REAL NOT NULL,
            desconto_proxima_fatura REAL DEFAULT 0
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS indicacoes (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            id_indicador INTEGER NOT NULL,
            id_indicado INTEGER,
            status TEXT NOT NULL,
            FOREIGN KEY (id_indicador) REFERENCES clientes (id),
            FOREIGN KEY (id_indicado) REFERENCES clientes (id)
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# --- Endpoints da API (ajustados para PostgreSQL) ---
# A principal mudança é o uso de '%s' como placeholder nas queries SQL.

@app.route('/clientes', methods=['POST'])
def criar_cliente():
    dados = request.json
    codigo_indicacao = dados.get('codigo_indicacao')
    conn = get_db_connection()
    cur = conn.cursor()
    desconto_inicial = 0
    indicacao_id = None

    if codigo_indicacao:
        cur.execute('SELECT id FROM indicacoes WHERE codigo = %s AND status = %s', (codigo_indicacao, 'pendente'))
        indicacao_encontrada = cur.fetchone()
        if indicacao_encontrada:
            desconto_inicial = 0.10
            indicacao_id = indicacao_encontrada[0]

    try:
        cur.execute(
            'INSERT INTO clientes (nome, email, valor_mensalidade, desconto_proxima_fatura) VALUES (%s, %s, %s, %s) RETURNING id',
            (dados['nome'], dados['email'], dados['valor_mensalidade'], desconto_inicial)
        )
        novo_cliente_id = cur.fetchone()[0]

        if indicacao_id:
            cur.execute('UPDATE indicacoes SET id_indicado = %s WHERE id = %s', (novo_cliente_id, indicacao_id))

        conn.commit()
        return jsonify({'id': novo_cliente_id, 'nome': dados['nome'], 'desconto_aplicado': f"{desconto_inicial*100}%"}), 201
    except psycopg2.IntegrityError:
        return jsonify({'erro': 'Email já cadastrado'}), 400
    finally:
        cur.close()
        conn.close()

@app.route('/gerar-codigo', methods=['POST'])
def gerar_codigo():
    id_cliente = request.json['id_cliente']
    codigo = str(uuid.uuid4())[:8].upper()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO indicacoes (codigo, id_indicador, status) VALUES (%s, %s, %s)',
            (codigo, id_cliente, 'pendente')
        )
        conn.commit()
        return jsonify({'codigo_gerado': codigo}), 201
    finally:
        cur.close()
        conn.close()

@app.route('/confirmar-pagamento', methods=['POST'])
def confirmar_pagamento():
    id_cliente_indicado = request.json['id_cliente_indicado']
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, id_indicador FROM indicacoes WHERE id_indicado = %s AND status = %s', (id_cliente_indicado, 'pendente'))
    indicacao = cur.fetchone()
    
    if not indicacao:
        cur.close()
        conn.close()
        return jsonify({'erro': 'Nenhuma indicação pendente encontrada para este cliente'}), 404

    indicacao_id, id_indicador = indicacao[0], indicacao[1]
    
    try:
        cur.execute('UPDATE clientes SET desconto_proxima_fatura = desconto_proxima_fatura + 0.15 WHERE id = %s', (id_indicador,))
        cur.execute('UPDATE indicacoes SET status = %s WHERE id = %s', ('confirmado', indicacao_id))
        conn.commit()
        return jsonify({'mensagem': f'Recompensa de 15% creditada ao indicador ID {id_indicador}'}), 200
    finally:
        cur.close()
        conn.close()

@app.route('/faturar-cliente', methods=['POST'])
def faturar_cliente():
    id_cliente = request.json['id_cliente']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM clientes WHERE id = %s', (id_cliente,))
    cliente = cur.fetchone()

    if not cliente:
        cur.close()
        conn.close()
        return jsonify({'erro': 'Cliente não encontrado'}), 404

    valor_final = cliente['valor_mensalidade'] * (1 - cliente['desconto_proxima_fatura'])
    valor_final = max(0, valor_final)

    cur.execute('UPDATE clientes SET desconto_proxima_fatura = 0 WHERE id = %s', (id_cliente,))
    conn.commit()
    
    # ... (restante da lógica igual)
    
    cur.close()
    conn.close()
    return jsonify({
        'mensagem': 'Fatura gerada e descontos aplicados com sucesso.',
        'cliente_id': id_cliente,
        # ... (restante do json igual)
    }), 200

# --- Inicialização ---
# Esta parte é executada apenas uma vez quando o serviço na Render é iniciado pela primeira vez.
with app.app_context():
    init_db()