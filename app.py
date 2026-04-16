import oracledb
import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}})

def get_connection():
    try:
        connection = oracledb.connect(
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            dsn=os.environ.get("DB_DSN")
        )
        return connection
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão"}), 500
    
    try:
        cursor = conn.cursor()
        query = """
            SELECT 
                u.ID, 
                u.NOME, 
                u.SALDO,
                (SELECT TIPO FROM INSCRICOES WHERE USUARIO_ID = u.ID AND ROWNUM = 1) as TIPO,
                (SELECT COUNT(*) FROM INSCRICOES WHERE USUARIO_ID = u.ID AND STATUS = 'PRESENT') as PRESENCAS
            FROM USUARIOS u
            ORDER BY u.ID
        """
        cursor.execute(query)
        
        usuarios = []
        for row in cursor.fetchall():
            usuarios.append({
                "id": row[0],
                "nome": row[1],
                "saldo": f"{row[2]:.2f}",
                "tipo": row[3] if row[3] else "NORMAL",
                "presencas": row[4] if row[4] is not None else 0
            })
        return jsonify(usuarios)
    finally:
        conn.close()

@app.route('/distribuir', methods=['POST'])
def distribuir_cashback():
    data = request.get_json()
    usuario_id = data.get('id')

    if not usuario_id:
        return jsonify({"status": "erro", "message": "ID do usuário não fornecido."}), 400

    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão com o banco"}), 500
    
    try:
        cursor = conn.cursor()
        plsql_block = """
        DECLARE
            CURSOR c_premiacao IS
                SELECT i.ID as inscricao_id, u.ID as user_id, i.VALOR_PAGO, i.TIPO
                FROM USUARIOS u
                JOIN INSCRICOES i ON u.ID = i.USUARIO_ID
                WHERE i.STATUS = 'PRESENT' AND u.ID = :user_id_param;
            
            v_total_presencas NUMBER;
            v_percentual NUMBER;
            v_cashback NUMBER;
            v_count NUMBER := 0;
        BEGIN
            FOR reg IN c_premiacao LOOP
                v_count := v_count + 1;
                
                -- Conta presenças totais para definir o bônus
                SELECT COUNT(*) INTO v_total_presencas 
                FROM INSCRICOES 
                WHERE USUARIO_ID = reg.user_id AND STATUS = 'PRESENT';

                -- Regras de Negócio
                IF v_total_presencas > 3 THEN
                    v_percentual := 0.25;
                ELSIF reg.TIPO = 'VIP' THEN
                    v_percentual := 0.20;
                ELSE
                    v_percentual := 0.10;
                END IF;

                v_cashback := reg.VALOR_PAGO * v_percentual;

                -- Atualiza o saldo do usuário
                UPDATE USUARIOS SET SALDO = SALDO + v_cashback WHERE ID = reg.user_id;
                
                -- Registra a auditoria
                INSERT INTO LOG_AUDITORIA (INSCRICAO_ID, MOTIVO, DATA)
                VALUES (reg.inscricao_id, 'CASHBACK INDIVIDUAL ' || (v_percentual*100) || '%', SYSDATE);
            END LOOP;
            
            IF v_count = 0 THEN
                RAISE_APPLICATION_ERROR(-20001, 'Usuário não encontrado ou sem presenças confirmadas.');
            END IF;

            COMMIT;
        END;
        """
        
        cursor.execute(plsql_block, user_id_param=usuario_id)
        return jsonify({"status": "sucesso", "message": f"Cashback aplicado com sucesso ao ID {usuario_id}!"})
    
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        return jsonify({"status": "erro", "message": error_obj.message}), 500
    except Exception as e:
        return jsonify({"status": "erro", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/reset', methods=['POST'])
def resetar_dados():
    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão"}), 500
    
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM LOG_AUDITORIA")
        cursor.execute("UPDATE USUARIOS SET SALDO = 100")
        
        conn.commit()
        return jsonify({"status": "sucesso", "message": "Sistema resetado: saldos voltaram para R$ 100.00."})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "erro", "message": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)