# src/etl_pipeline/main.py
import pandas as pd
import requests
import os
import re
from dotenv import load_dotenv
from fpdf import FPDF

load_dotenv(override=True)

# --- DICTIONARY MONTHS
MAPA_MESES = {
    'JANEIRO': ('01', 'JAN'),
    'FEVEREIRO': ('02', 'FEV'),
    'MARÇO': ('03', 'MAR'),
    'ABRIL': ('04', 'ABR'),
    'MAIO': ('05', 'MAI'),
    'JUNHO': ('06', 'JUN'),
    'JULHO': ('07', 'JUL'),
    'AGOSTO': ('08', 'AGO'),
    'SETEMBRO': ('09', 'SET'),
    'OUTUBRO': ('10', 'OUT'),
    'NOVEMBRO': ('11', 'NOV'),
    'DEZEMBRO': ('12', 'DEZ')
}


# --- FUNCTION TO CLEAN THE RAW DATA AND EXTRACT THE CPFS ---
def clean_raw_data(file_path):
    print(f"Read raw file: {file_path}")
    # Change to pd.read_excel if downloading as .xlsx
    df = pd.read_csv(file_path, header=None, dtype=str)

    # =========================================================
    # DETETIVE DO MÊS E ANO (Procura ANTES de limpar o lixo do ficheiro)
    # =========================================================
    periodo = {'ano_mes': '2026/01', 'abrev': 'JAN', 'ano': '2026'}

    mask_folha = df[0].str.contains(
        'FOLHA DE PAGAMENTO DE', case=False, na=False)
    if mask_folha.any():
        texto_folha = str(df.loc[mask_folha, 0].values[0]).upper()
        match = re.search(
            r'FOLHA DE PAGAMENTO DE\s+([A-ZÇ]+)\s+DE\s+(\d{4})', texto_folha)
        if match:
            mes_extenso = match.group(1).strip()
            ano_valor = match.group(2)
            numero_mes, mes_abrev = MAPA_MESES.get(
                mes_extenso, ('00', mes_extenso[:3]))
            periodo['ano_mes'] = f"{ano_valor}/{numero_mes}"
            periodo['abrev'] = mes_abrev
            periodo['ano'] = ano_valor
    # =========================================================

    # Initial exploration of the raw data
    print(f"Initial rows in raw data: {len(df)}")
    print("Columns in raw data:", df.columns.tolist())

    # --- STEP A: EXTRACT THE TYPE OF ASSISTANCE ---
    mask_auxilio = df[0].str.contains('TIPO DE AUXÍLIO:', case=False, na=False)
    df.loc[mask_auxilio, 'tipo_auxilio'] = df.loc[mask_auxilio,
                                                  0].str.replace(r'(?i)TIPO DE AUXÍLIO:\s*', '', regex=True)
    df['tipo_auxilio'] = df['tipo_auxilio'].ffill()

    mask_header = df[2] == 'CPF'

    if not mask_header.any():
        print("Error: No header row with 'CPF' found. Please check the input file format.")
        return [], None

    header_index = df[mask_header].index[0]

    header_names = df.iloc[header_index].tolist()

    # Ensure the last column is named 'tipo_auxilio'
    header_names[-1] = 'tipo_auxilio'
    df.columns = header_names

    df = df.iloc[header_index + 1:].copy()

    # --- STEP B: FORMAT CPFS ---
    df['cpf_limpo'] = df['CPF'].astype(str)

    # Remove as linhas vazias ANTES de limpar os números
    df = df[~df['cpf_limpo'].str.contains('nan|None', regex=True, na=False)]

    # Substitui tudo que não for número (\D) por vazio, tirando pontos e traços
    df['cpf_limpo'] = df['cpf_limpo'].str.replace(r'\D', '', regex=True)

    # Preenche com zeros à esquerda para garantir os 11 dígitos
    df['cpf_limpo'] = df['cpf_limpo'].str.zfill(11)

    print(f"Cleaning completed! {len(df)} valid CPFs found.")
    return df['cpf_limpo'].tolist(), df, periodo


def fetch_metabase_data(missing_cpfs):
    if not missing_cpfs:
        print("No missing CPFs. Skipping Metabase.")
        return None

    print(f"Fetching {len(missing_cpfs)} students from Metabase...")
    base_url = "http://132.255.99.40:3001"

    print(f"Debug: Tentando logar com usuário: {os.getenv('METABASE_USER')}")

    # 1. Autenticação
    auth_payload = {
        "username": os.getenv("METABASE_USER"),
        "password": os.getenv("METABASE_PASS")
    }
    session_res = requests.post(
        f"{base_url}/api/session", json=auth_payload, verify=False)

    if session_res.status_code != 200:
        print(f"ERRO NA AUTENTICAÇÃO! Status: {session_res.status_code}")
        print("Resposta:", session_res.text)
        return None

    token = session_res.json().get("id")
    headers = {"Content-Type": "application/json", "X-Metabase-Session": token}

    # =========================================================
    # RADAR DE BANCOS DE DADOS (Imprime antes de fazer a query)
    # =========================================================
    print("\n--- Bancos de Dados Disponíveis no seu Metabase ---")
    db_res = requests.get(f"{base_url}/api/database",
                          headers=headers, verify=False)
    if db_res.status_code == 200:
        databases = db_res.json()
        if isinstance(databases, dict) and "data" in databases:
            databases = databases["data"]
        for db in databases:
            if isinstance(db, dict) and "id" in db and "name" in db:
                print(f"ID: {db['id']} -> Nome: {db['name']}")
    print("---------------------------------------------------\n")
    # =========================================================

    # 2. Query
    cpfs_formatted = ",".join([str(cpf)
                              for cpf in missing_cpfs if str(cpf).isdigit()])

    sql_query = rf"""
        WITH variaveis AS (
        SELECT 1502.00 AS salario_minimo
    ),
    dados_com_prioridade AS (
        SELECT DISTINCT
            discente.matricula
            ,curso.nome AS curso
            ,munic_campus.nome AS campus
            ,regexp_replace(
                lpad(cast(pessoa.cpf_cnpj AS varchar), 11, '0'),
                '(\d{{3}})(\d{{3}})(\d{{3}})(\d{{2}})',
                '\1.\2.\3-\4'
            ) AS cpf_formatado
            ,pessoa.nome
            ,pessoa.data_nascimento
            ,LOWER(usuario.email) AS email
            ,CASE
                WHEN pessoa.sexo = 'M' THEN '1'
                WHEN pessoa.sexo = 'F' THEN '2'
                ELSE '3'
            END sexo
            ,COALESCE(tipo_raca.codigo_inep, '6') AS raca_cor
            ,CASE
                WHEN tipo_etnia.descricao = 'Indígena' THEN '1'
                WHEN tipo_etnia.descricao = 'Quilombola' THEN '2'
                WHEN tipo_etnia.descricao = 'Comunidades tradicionais' THEN '3'
                ELSE '4'
            END etinia
            ,CASE
                WHEN pais.nome = 'Brasil' AND pessoa.pais_nacionalidade ILIKE 'brasil%' THEN '1'
                WHEN pais.nome <> 'Brasil' AND pessoa.pais_nacionalidade ILIKE 'brasil%' THEN '2'
                ELSE '3'
            END nacionalide
            ,'2' deficiencia
            ,'2' transtornos_globais
            ,'2' superdotacao
            ,situacao_socio_economica_discente.quantidade_membros_familia quantidade_de_membros_da_unidade_familiar
            ,CASE
                WHEN situacao_socio_economica_discente.quantidade_membros_familia IS NULL OR situacao_socio_economica_discente.quantidade_membros_familia = 0 THEN '4'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) <= (variaveis.salario_minimo * 0.5) THEN '1'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) <= (variaveis.salario_minimo) THEN '2'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) <= (variaveis.salario_minimo * 1.5) THEN '3'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) <= (variaveis.salario_minimo * 2.5) THEN '5'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) <= (variaveis.salario_minimo * 3.5) THEN '6'
                WHEN (situacao_socio_economica_discente.renda_familiar / situacao_socio_economica_discente.quantidade_membros_familia) > (variaveis.salario_minimo * 3.5) THEN '7'
                ELSE '4'
            END faixa_familiar_percapita
            ,curso.id_curso
            ,curso.codigo_inep
            ,CASE
                WHEN curso.nivel = 'EM' THEN '1'
                WHEN curso.nivel IN ('G', 'L') THEN '2'
                WHEN curso.nivel = 'PGLS' THEN '3'
                WHEN curso.nivel = 'E' THEN '4'
                WHEN curso.nivel = 'DOUT' THEN '5'
                WHEN curso.nivel = 'D' THEN '6'
                ELSE '0'
            END nivel
            ,CASE
                WHEN discente.status = 1 THEN 'ATIVO'
                WHEN discente.status = 2 THEN 'CADASTRADO'
                WHEN discente.status = 3 THEN 'CONCLUIDO'
                WHEN discente.status = 4 THEN 'AFASTADO'
                WHEN discente.status = 5 THEN 'TRANCADO'
                WHEN discente.status = 6 THEN 'CANCELADO'
                WHEN discente.status = 7 THEN 'JUBILADO'
                WHEN discente.status = 8 THEN 'FORMANDO'
                WHEN discente.status = 9 THEN 'GRADUANDO'
                WHEN discente.status = 10 THEN 'EXCLUIDO'
                WHEN discente.status = 11 THEN 'EM_HOMOLOGACAO'
            END AS status
            
            -- >>> A MÁGICA DA PRIORIDADE ACONTECE AQUI <<<
            ,ROW_NUMBER() OVER (
                PARTITION BY pessoa.cpf_cnpj 
                ORDER BY 
                    CASE discente.status
                        WHEN 1 THEN 1  -- 1º ATIVO
                        WHEN 9 THEN 2  -- 2º GRADUANDO
                        WHEN 8 THEN 3  -- 3º FORMANDO
                        WHEN 11 THEN 4 -- 4º EM HOMOLOGACAO
                        WHEN 2 THEN 5  -- 5º CADASTRADO
                        WHEN 5 THEN 6  -- 6º TRANCADO
                        WHEN 3 THEN 7  -- 7º CONCLUIDO
                        WHEN 4 THEN 8  -- 8º AFASTADO
                        WHEN 6 THEN 9  -- 9º CANCELADO
                        WHEN 7 THEN 10 -- 10º JUBILADO
                        WHEN 10 THEN 11 -- 11º EXCLUIDO
                        ELSE 99 
                    END ASC,
                    discente.matricula DESC -- Desempate: Se tiver dois com o mesmo status, pega a matrícula mais recente (maior)
            ) as rank_matricula
        FROM
            public.discente
            INNER JOIN public.curso ON curso.id_curso = discente.id_curso
            INNER JOIN comum.pessoa ON pessoa.id_pessoa = discente.id_pessoa
            INNER JOIN comum.usuario ON usuario.id_pessoa = pessoa.id_pessoa
            INNER JOIN comum.pais ON pais.id_pais = pessoa.id_pais_nacionalidade
            INNER JOIN comum.tipo_raca ON tipo_raca.id_tipo_raca = pessoa.id_raca
            LEFT JOIN comum.municipio munic_campus ON munic_campus.id_municipio = curso.id_municipio
            LEFT JOIN comum.tipo_etnia ON tipo_etnia.id_tipo_etnia = pessoa.id_tipo_etnia
            LEFT JOIN sae.situacao_socio_economica_discente ON situacao_socio_economica_discente.id_discente = discente.id_discente
            LEFT JOIN public.status_discente ON status_discente.status = discente.status
            CROSS JOIN variaveis
        WHERE
            pessoa.cpf_cnpj IN ({cpfs_formatted})
    )
    -- Selecionamos apenas a linha que ficou em 1º lugar no ranking de prioridade para cada CPF
    SELECT * FROM dados_com_prioridade 
    WHERE rank_matricula = 1
    """
    query_payload = {
        "query": {
            "database": 3,
            "type": "native",
            "native": {"query": sql_query}
        }
    }

    # 3. Requisição do Dataset
    data_res = requests.post(
        f"{base_url}/api/dataset/json", json=query_payload, headers=headers, verify=False)

    if data_res.status_code != 200:
        print(f"ERRO NA QUERY! Status: {data_res.status_code}")
        print("Resposta do servidor:", data_res.text[:1000])
        return None

    # 4. Leitura Robusta do Pandas
    resposta_json = data_res.json()

    # Verifica o formato que o Metabase enviou
    if isinstance(resposta_json, dict):
        if "error" in resposta_json:
            print("Erro do banco de dados:", resposta_json["error"])
            return pd.DataFrame()
        elif "data" in resposta_json:
            # Padrão tradicional: Extrai as colunas e as linhas de dentro do pacote "data"
            rows = resposta_json["data"].get("rows", [])
            cols = [col["name"]
                    for col in resposta_json["data"].get("cols", [])]
            metabase_df = pd.DataFrame(rows, columns=cols)
        else:
            print("Resposta inesperada do Metabase:", str(resposta_json)[:500])
            return pd.DataFrame()
    elif isinstance(resposta_json, list):
        # Padrão simplificado de lista
        metabase_df = pd.DataFrame(resposta_json)
    else:
        metabase_df = pd.DataFrame()

    # Se a tabela estiver vazia
    if metabase_df.empty:
        print("A query rodou com sucesso, mas o SIG-ADMINISTRATIVO retornou 0 resultados para esses CPFs.")
        return metabase_df

    print(
        f"Data from Metabase downloaded successfully! ({len(metabase_df)} alunos encontrados)")
    return metabase_df


# --- CLASSE DO PDF COM CABEÇALHO E RODAPÉ AUTOMÁTICOS ---
class RelatorioTransparencia(FPDF):
    def header(self):
        # ==========================================
        # 1. CABEÇALHO INSTITUCIONAL (Automático)
        # ==========================================

        # Insere a logo (Descomente a linha abaixo e coloque o nome correto da imagem)
        caminho_logo = os.path.join(
            os.getcwd(), 'input', 'logo-oficial-unifap4.png')
        if os.path.exists(caminho_logo):
            # x e y definem a posição da margem, w é a largura da imagem (em mm)
            self.image(caminho_logo, x=15, y=8, w=12)

        # Posiciona o cursor para os textos
        self.set_y(10)

        # Título Principal (Instituição)
        self.set_font('helvetica', 'B', 12)
        self.cell(0, 5, 'UNIVERSIDADE FEDERAL DO AMAPÁ - UNIFAP', align='C')
        self.ln(5)

        # Subtítulo (Departamento / Pró-Reitoria) - Ajuste o nome conforme necessário
        self.set_font('helvetica', '', 10)
        self.cell(0, 5, 'DEPARTAMENTO DE ASSISTÊNCIA ESTUDANTIL - DACE', align='C')
        self.ln(5)

        # Título do Relatório
        self.set_font('helvetica', 'B', 10)
        self.cell(
            0, 5, 'PORTAL DE TRANSPARÊNCIA - PAGAMENTO DE AUXÍLIOS', align='C')
        self.ln(12)  # Dá um espaço generoso antes de começar a tabela

        # ==========================================
        # 2. CABEÇALHO DA TABELA (Repete em toda página)
        # ==========================================
        self.set_font('helvetica', 'B', 8)
        col_widths = [65, 25, 25, 55, 30, 45, 15, 17]
        headers = ['Nome', 'cpf', 'matricula', 'curso',
                   'campus', 'Auxílio', 'ano_mes', 'Valor R$']

        for i, header_nome in enumerate(headers):
            self.cell(col_widths[i], 8, header_nome, border=1, align='C')
        self.ln()

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        # Coloca a data de geração do lado esquerdo e a página do lado direito
        data_atual = pd.Timestamp.now().strftime('%d/%m/%Y %H:%M')
        self.cell(
            0, 10, f'Documento gerado em: {data_atual}', align='L')

        # Volta o cursor para a mesma linha para alinhar a página à direita
        self.set_x(self.l_margin)
        self.cell(0, 10, f'Página {self.page_no()}/{{nb}}', align='R')

# --- FUNÇÃO DE TRANSFORMAÇÃO E EXPORTAÇÃO ---


def gerar_relatorios_transparencia(df_bruto, df_metabase, out_dir, periodo):
    print("\n" + "="*40)
    print("CRUZANDO DADOS E GERANDO RELATÓRIOS...")

    # =========================================================
    # SEARCHING MONTH AND YEAR IN THE RAW FILENAME (for dynamic naming of output files)
    # =========================================================

    ano_mes_valor = periodo['ano_mes']
    mes_abrev = periodo['abrev']
    ano_valor = periodo['ano']

    # 1. Prepara o CPF do Metabase para o cruzamento (remove pontos e traços)
    df_metabase['cpf_limpo'] = df_metabase['cpf_formatado'].str.replace(
        r'\D', '', regex=True)

    # 2. O CRUZAMENTO (PROCV/Merge) usando o cpf_limpo
    df_cruzado = pd.merge(df_bruto, df_metabase, on='cpf_limpo', how='inner')

    # 3. Montar a Tabela Final com as colunas exatas solicitadas
    df_final = pd.DataFrame()
    df_final['Nome'] = df_cruzado['nome']
    df_final['cpf'] = df_cruzado['cpf_limpo'].apply(
        lambda x: f"***.{str(x)[3:6]}.{str(x)[6:9]}-**")
    df_final['matricula'] = df_cruzado['matricula']
    df_final['curso'] = df_cruzado['curso']
    df_final['campus'] = df_cruzado['campus']
    df_final['Auxílio'] = df_cruzado['tipo_auxilio']
    df_final['ano_mes'] = ano_mes_valor

    # IMPORTANTE: No CSV original as colunas são números [0, 1, 2, ...].
    # Vou assumir que o 'VALOR' está na coluna 6. AJUSTE O '6' ABAIXO SE FOR OUTRA COLUNA!
    def formata_moeda(valor):
        try:
            # Tenta limpar caracteres estranhos e transformar em float
            val_limpo = str(valor).replace('R$', '').replace(
                '.', '').replace(',', '.').strip()
            return f"R$ {float(val_limpo):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        except:
            return valor

    # --- A MÁGICA PARA ACHAR A COLUNA DE VALOR DINAMICAMENTE ---
    # Procura em todas as colunas da planilha por alguma que contenha a palavra "VALOR"
    nome_coluna_valor = None
    for col in df_bruto.columns:
        if 'VALOR' in str(col).upper():
            nome_coluna_valor = col
            break

    # Se por algum motivo o cabeçalho vier diferente e não achar "VALOR", usa o nome exato
    if not nome_coluna_valor:
        nome_coluna_valor = 'Valor R$'

    # Aplica a formatação usando a coluna encontrada
    df_final['Valor R$'] = df_cruzado[nome_coluna_valor].apply(formata_moeda)

    # --- EXPORTAR EXCEL ---
    # Ex: PORTAL-TRANSPARENCIA-FEV-2026
    nome_ficheiro_base = f'PORTAL-TRANSPARENCIA-{mes_abrev}-{ano_valor}'
    caminho_xlsx = os.path.join(out_dir, f'{nome_ficheiro_base}.xlsx')
    df_final.to_excel(caminho_xlsx, index=False)

    print(f"✅ Excel gerado: {caminho_xlsx}")

    # --- EXPORTAR PDF ---
    caminho_pdf = os.path.join(out_dir, f'{nome_ficheiro_base}.pdf')
    pdf = RelatorioTransparencia(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font('helvetica', '', 7)

    col_widths = [65, 25, 25, 55, 30, 45, 15, 17]

    # 1. Definimos o limite máximo de caracteres seguro para cada coluna (para não encavalar)
    # Colunas:   Nome, CPF, Matr, Curso, Campus, Auxilio, AnoMes, Valor
    max_chars = [48,   18,  15,   38,    22,     35,      12,     15]

    for index, row in df_final.iterrows():
        for i, val in enumerate(row):
            texto = str(val).strip()

            # 2. Se o texto for maior que o limite daquela coluna específica, corta e coloca "..."
            if len(texto) > max_chars[i]:
                texto = texto[:max_chars[i]-3] + "..."

            # 3. BÔNUS DE ESTÉTICA: Centraliza números e datas, e alinha textos à esquerda
            alinhamento = 'C' if i in [1, 2, 6, 7] else 'L'

            pdf.cell(col_widths[i], 6, texto, border=1, align=alinhamento)
        pdf.ln()

    pdf.output(caminho_pdf)
    print(f"✅ PDF gerado: {caminho_pdf}")
    print("="*40)


def run_pipeline():
    print("="*40)
    print("Initializing ETL Pipeline - UNIFAP (Múltiplos Ficheiros)")
    print("="*40)

    # Configure directories
    base_dir = os.getcwd()
    input_dir = os.path.join(base_dir, 'input')
    out_dir = os.path.join(base_dir, 'out')

    # Create directories if they don't exist
    os.makedirs(input_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # Configure the input directory with the raw files (CSV or Excel)
    # that you want to process. You can drop multiple files here and
    # the pipeline will process them one by one.
    # Ex.: input/folha_fev_2026.csv, input/folha_mar_2026.csv, etc.
    arquivos_csv = [f for f in os.listdir(
        input_dir) if f.lower().endswith('.csv')]

    if not arquivos_csv:
        print("Aviso: Nenhum ficheiro CSV encontrado na pasta 'input'.")
        return

    print(
        f"Lote encontrado: {len(arquivos_csv)} ficheiro(s) para processar.\n")

    # 2. Inicia o ciclo para processar cada ficheiro um a um
    for arquivo in arquivos_csv:
        print("\n" + "#"*60)
        print(f"🚀 INICIANDO PROCESSAMENTO: {arquivo}")
        print("#"*60)

        raw_file = os.path.join(input_dir, arquivo)

        # Limpa os dados deste ficheiro específico
        list_cpfs, df_limpo, periodo_ficheiro = clean_raw_data(raw_file)

        # Se o ficheiro estiver vazio ou inválido, avança para o próximo
        if not list_cpfs:
            print(f"⚠️ O ficheiro {arquivo} não tem CPFs válidos. Saltando...")
            continue

        cpfs_missing = list_cpfs

        # Busca no Metabase
        df_novos_alunos = fetch_metabase_data(cpfs_missing)

        # Se tiver sucesso, gera os relatórios
        if df_novos_alunos is not None and not df_novos_alunos.empty:
            gerar_relatorios_transparencia(
                df_limpo, df_novos_alunos, out_dir, periodo_ficheiro)
        else:
            print(
                f"Atenção: Não há dados no Metabase para gerar os relatórios de {arquivo}.")

    print(f"✅ Processamento de {arquivo} concluído!")


if __name__ == "__main__":
    run_pipeline()
