import os
import requests
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes
)


# =========================================================
# CONFIGURAÇÕES
# =========================================================

TOKEN = os.environ["TELEGRAM_TOKEN"]
SOLANA_RPC = os.environ["SOLANA_RPC"]


# =========================================================
# SOLANA RPC
# =========================================================

def solana_rpc(method, params):

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }

    response = requests.post(
        SOLANA_RPC,
        json=payload,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise Exception(data["error"])

    return data.get("result")


# =========================================================
# DADOS DE LIQUIDEZ / DEXSCREENER
# =========================================================

def get_liquidity_data(token_address):

    url = (
        "https://api.dexscreener.com/latest/dex/tokens/"
        f"{token_address}"
    )

    response = requests.get(
        url,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    pairs = data.get(
        "pairs",
        []
    )

    solana_pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == "solana"
    ]

    if not solana_pairs:
        return None

    best_pair = max(
        solana_pairs,
        key=lambda pair: (
            pair.get(
                "liquidity",
                {}
            ).get("usd") or 0
        )
    )

    liquidity = (
        best_pair
        .get("liquidity", {})
        .get("usd") or 0
    )

    market_cap = (
        best_pair.get("marketCap")
        or best_pair.get("fdv")
        or 0
    )

    volume_24h = (
        best_pair
        .get("volume", {})
        .get("h24") or 0
    )

    price_change_24h = (
        best_pair
        .get("priceChange", {})
        .get("h24") or 0
    )

    dex_id = best_pair.get(
        "dexId",
        "N/D"
    )

    pair_address = best_pair.get(
        "pairAddress",
        "N/D"
    )

    return {
        "liquidity": float(liquidity),
        "market_cap": float(market_cap),
        "volume_24h": float(volume_24h),
        "price_change_24h": float(price_change_24h),
        "dex_id": dex_id,
        "pair_address": pair_address
    }


# =========================================================
# IDENTIFICAR OWNER DE TOKEN ACCOUNT
# =========================================================

def get_token_account_owner(
    token_account_address
):

    result = solana_rpc(
        "getAccountInfo",
        [
            token_account_address,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed"
            }
        ]
    )

    if not result:
        return None

    account = result.get(
        "value"
    )

    if not account:
        return None

    data = account.get(
        "data",
        {}
    )

    parsed = data.get(
        "parsed",
        {}
    )

    info = parsed.get(
        "info",
        {}
    )

    owner = info.get(
        "owner"
    )

    return owner


# =========================================================
# VERIFICAR SE É A POOL
# =========================================================

def is_liquidity_pool_wallet(
    wallet_address,
    pair_address
):

    if not wallet_address:
        return False

    if not pair_address:
        return False

    if pair_address == "N/D":
        return False

    return wallet_address == pair_address


# =========================================================
# FORMATAR DATA
# =========================================================

def format_timestamp(timestamp):

    if not timestamp:
        return "N/D"

    try:

        date = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc
        )

        return date.strftime(
            "%d/%m/%Y %H:%M UTC"
        )

    except Exception:

        return "N/D"


# =========================================================
# BUSCAR HISTÓRICO DO MINT
# =========================================================

def get_mint_signatures(
    token_address,
    limit=20
):

    result = solana_rpc(
        "getSignaturesForAddress",
        [
            token_address,
            {
                "limit": limit,
                "commitment": "confirmed"
            }
        ]
    )

    if not result:
        return []

    return result


# =========================================================
# BUSCAR TRANSAÇÃO
# =========================================================

def get_transaction(
    signature
):

    result = solana_rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "commitment": "confirmed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    )

    return result


# =========================================================
# IDENTIFICAR SIGNATÁRIOS
# =========================================================

def get_transaction_signers(
    transaction
):

    if not transaction:
        return []

    tx = transaction.get(
        "transaction",
        {}
    )

    message = tx.get(
        "message",
        {}
    )

    account_keys = message.get(
        "accountKeys",
        []
    )

    signers = []

    for account in account_keys:

        if isinstance(
            account,
            dict
        ):

            if account.get(
                "signer"
            ):

                pubkey = account.get(
                    "pubkey"
                )

                if pubkey:
                    signers.append(
                        pubkey
                    )

        elif isinstance(
            account,
            str
        ):

            # Fallback para resposta não-parsed
            if account not in signers:
                signers.append(account)

    return signers


# =========================================================
# IDENTIFICAR CANDIDATO A DEPLOYER
# =========================================================

def identify_deployer(
    token_address
):

    signatures = get_mint_signatures(
        token_address,
        limit=20
    )

    if not signatures:

        return {
            "wallet": None,
            "signature": None,
            "block_time": None,
            "signers": [],
            "confidence": "BAIXA",
            "reason": (
                "Nenhuma transação encontrada "
                "para o mint."
            )
        }

    # A API retorna do mais recente
    # para o mais antigo.
    #
    # Vamos analisar do mais antigo
    # para o mais recente.

    ordered_signatures = list(
        reversed(signatures)
    )

    first_successful_transaction = None
    first_signature = None
    first_block_time = None
    first_signers = []

    for item in ordered_signatures:

        if item.get("err") is not None:
            continue

        signature = item.get(
            "signature"
        )

        if not signature:
            continue

        try:

            transaction = get_transaction(
                signature
            )

        except Exception as error:

            print(
                "ERRO TRANSACTION:",
                repr(error)
            )

            continue

        if not transaction:
            continue

        signers = get_transaction_signers(
            transaction
        )

        if not signers:
            continue

        first_successful_transaction = (
            transaction
        )

        first_signature = signature

        first_block_time = (
            item.get("blockTime")
        )

        first_signers = signers

        break

    if not first_successful_transaction:

        return {
            "wallet": None,
            "signature": None,
            "block_time": None,
            "signers": [],
            "confidence": "BAIXA",
            "reason": (
                "Não foi possível identificar "
                "um signatário da atividade inicial."
            )
        }

    # O primeiro signer da transação é
    # tratado apenas como CANDIDATO.
    candidate = first_signers[0]

    if len(first_signers) == 1:

        confidence = "MÉDIA"

    else:

        confidence = "BAIXA"

    return {
        "wallet": candidate,
        "signature": first_signature,
        "block_time": first_block_time,
        "signers": first_signers,
        "confidence": confidence,
        "reason": (
            "Wallet identificada a partir do "
            "signatário da atividade inicial "
            "encontrada para o mint."
        )
    }


# =========================================================
# HISTÓRICO RECENTE DA DEV WALLET
# =========================================================

def get_wallet_activity(
    wallet_address,
    limit=20
):

    signatures = solana_rpc(
        "getSignaturesForAddress",
        [
            wallet_address,
            {
                "limit": limit,
                "commitment": "confirmed"
            }
        ]
    )

    if not signatures:
        return {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "first_seen": None,
            "last_seen": None
        }

    successful = 0
    failed = 0

    timestamps = []

    for item in signatures:

        if item.get("err"):

            failed += 1

        else:

            successful += 1

        block_time = item.get(
            "blockTime"
        )

        if block_time:
            timestamps.append(
                block_time
            )

    first_seen = None
    last_seen = None

    if timestamps:

        first_seen = min(
            timestamps
        )

        last_seen = max(
            timestamps
        )

    return {
        "total": len(signatures),
        "successful": successful,
        "failed": failed,
        "first_seen": first_seen,
        "last_seen": last_seen
    }


# =========================================================
# COMANDO START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 MEME RADAR AI\n\n"
        "Bot online e conectado à Solana.\n\n"
        "Comandos disponíveis:\n\n"
        "/top - Melhores oportunidades de mercado\n"
        "/security ENDERECO - Análise de segurança\n"
        "/help - Ajuda"
    )


# =========================================================
# COMANDO HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 MEME RADAR AI\n\n"

        "📊 /top\n"
        "Mostra os tokens com melhor atividade "
        "de mercado.\n\n"

        "🛡️ /security ENDERECO\n"
        "Analisa segurança, autoridades, holders, "
        "liquidez e carteira candidata do deployer.\n\n"

        "Exemplo:\n"
        "/security ENDERECO_DO_TOKEN\n\n"

        "⚠️ As análises são informativas e não "
        "garantem lucro."
    )


# =========================================================
# COMANDO TOP
# =========================================================

async def top(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📡 MEME RADAR AI\n\n"
        "🔎 Procurando oportunidades na Solana...\n"
        "⏳ Aguarde..."
    )

    try:

        profiles_url = (
            "https://api.dexscreener.com/"
            "token-profiles/latest/v1"
        )

        response = requests.get(
            profiles_url,
            timeout=20
        )

        response.raise_for_status()

        profiles = response.json()

        candidates = []

        for profile in profiles:

            if profile.get(
                "chainId"
            ) != "solana":

                continue

            token_address = profile.get(
                "tokenAddress"
            )

            if not token_address:
                continue

            try:

                token_url = (
                    "https://api.dexscreener.com/"
                    "latest/dex/tokens/"
                    f"{token_address}"
                )

                token_response = requests.get(
                    token_url,
                    timeout=15
                )

                token_response.raise_for_status()

                token_data = (
                    token_response.json()
                )

                pairs = token_data.get(
                    "pairs",
                    []
                )

                solana_pairs = [
                    pair
                    for pair in pairs
                    if pair.get(
                        "chainId"
                    ) == "solana"
                ]

                if not solana_pairs:
                    continue

                best_pair = max(
                    solana_pairs,
                    key=lambda pair: (
                        pair.get(
                            "liquidity",
                            {}
                        ).get("usd") or 0
                    )
                )

                base_token = best_pair.get(
                    "baseToken",
                    {}
                )

                symbol = base_token.get(
                    "symbol",
                    "N/D"
                )

                name = base_token.get(
                    "name",
                    "Token"
                )

                if symbol.upper() in [
                    "SOL",
                    "WSOL"
                ]:

                    continue

                liquidity = (
                    best_pair
                    .get("liquidity", {})
                    .get("usd") or 0
                )

                volume = (
                    best_pair
                    .get("volume", {})
                    .get("h24") or 0
                )

                price_change = (
                    best_pair
                    .get("priceChange", {})
                    .get("h24") or 0
                )

                market_cap = (
                    best_pair.get(
                        "marketCap"
                    )
                    or best_pair.get(
                        "fdv"
                    )
                    or 0
                )

                if liquidity < 15000:
                    continue

                if volume < 10000:
                    continue

                liquidity_score = min(
                    liquidity / 50000 * 30,
                    30
                )

                volume_score = min(
                    volume / 500000 * 30,
                    30
                )

                if price_change >= 50:

                    movement_score = 5

                elif price_change > 0:

                    movement_score = min(
                        price_change / 10,
                        20
                    )

                else:

                    movement_score = 0

                volume_liquidity_ratio = (
                    volume / liquidity
                    if liquidity > 0
                    else 0
                )

                ratio_score = min(
                    volume_liquidity_ratio / 10 * 20,
                    20
                )

                score = (
                    liquidity_score
                    + volume_score
                    + movement_score
                    + ratio_score
                )

                candidates.append({
                    "name": name,
                    "symbol": symbol,
                    "address": token_address,
                    "liquidity": liquidity,
                    "volume": volume,
                    "price_change": price_change,
                    "market_cap": market_cap,
                    "score": score
                })

            except Exception as token_error:

                print(
                    "ERRO TOKEN TOP:",
                    repr(token_error)
                )

                continue

            if len(candidates) >= 30:
                break

        candidates.sort(
            key=lambda item: item["score"],
            reverse=True
        )

        top_tokens = candidates[:5]

        if not top_tokens:

            await update.message.reply_text(
                "❌ Não encontrei tokens suficientes "
                "com os filtros atuais."
            )

            return

        message = (
            "🔥 MEME RADAR AI — TOP 5\n\n"

            "Ranking baseado em dados de mercado.\n"
            "Ainda não considera segurança, "
            "carteiras, comunidade ou notícias.\n\n"
        )

        for index, token in enumerate(
            top_tokens,
            start=1
        ):

            message += (
                f"{index}️⃣ {token['name']} "
                f"({token['symbol']})\n"

                f"📊 Score mercado: "
                f"{token['score']:.0f}/100\n"

                f"💧 Liquidez: "
                f"${token['liquidity']:,.0f}\n"

                f"📈 Volume 24h: "
                f"${token['volume']:,.0f}\n"

                f"🚀 Movimento: "
                f"{token['price_change']:.2f}%\n"

                f"💰 MC: "
                f"${token['market_cap']:,.0f}\n"

                f"🪙 `{token['address']}`\n\n"
            )

        message += (
            "⚠️ IMPORTANTE\n"

            "Esse ranking NÃO é sinal de compra.\n"

            "Um token pode ter volume alto e ainda "
            "ser extremamente arriscado.\n\n"

            "Próxima etapa: Security + Wallet "
            "Intelligence."
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except Exception as error:

        print(
            "ERRO TOP:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ Erro no Market Engine.\n\n"
            f"Detalhes: {error}"
        )


# =========================================================
# COMANDO SECURITY
# =========================================================

async def security(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "🛡️ Você precisa colocar o endereço "
            "do token.\n\n"

            "Exemplo:\n"
            "/security ENDERECO_DO_TOKEN"
        )

        return

    token_address = context.args[0]

    await update.message.reply_text(
        "🛡️ SECURITY ENGINE\n\n"
        "🔎 Consultando a blockchain Solana...\n"
        "⏳ Aguarde..."
    )

    try:

        # =====================================================
        # 1. DADOS DO MINT
        # =====================================================

        result = solana_rpc(
            "getAccountInfo",
            [
                token_address,
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed"
                }
            ]
        )

        account = (
            result.get("value")
            if result
            else None
        )

        if not account:

            await update.message.reply_text(
                "❌ Não encontrei esse endereço "
                "na blockchain Solana."
            )

            return

        data = account.get(
            "data",
            {}
        )

        parsed = data.get(
            "parsed",
            {}
        )

        info = parsed.get(
            "info",
            {}
        )

        mint_authority = info.get(
            "mintAuthority"
        )

        freeze_authority = info.get(
            "freezeAuthority"
        )

        supply = info.get(
            "supply",
            "0"
        )

        decimals = info.get(
            "decimals",
            0
        )

        owner_program = account.get(
            "owner",
            "N/D"
        )

        if mint_authority:

            mint_status = "⚠️ ATIVA"

        else:

            mint_status = "✅ REVOGADA"

        if freeze_authority:

            freeze_status = "⚠️ ATIVA"

        else:

            freeze_status = "✅ REVOGADA"

        # =====================================================
        # 2. LIQUIDEZ
        # =====================================================

        liquidity_data = get_liquidity_data(
            token_address
        )

        liquidity = 0
        market_cap = 0
        volume_24h = 0
        price_change = 0
        dex_id = "N/D"
        pair_address = "N/D"

        if liquidity_data:

            liquidity = (
                liquidity_data["liquidity"]
            )

            market_cap = (
                liquidity_data["market_cap"]
            )

            volume_24h = (
                liquidity_data["volume_24h"]
            )

            price_change = (
                liquidity_data["price_change_24h"]
            )

            dex_id = (
                liquidity_data["dex_id"]
            )

            pair_address = (
                liquidity_data["pair_address"]
            )

        # =====================================================
        # 3. MAIORES CONTAS
        # =====================================================

        largest_result = solana_rpc(
            "getTokenLargestAccounts",
            [
                token_address,
                {
                    "commitment": "confirmed"
                }
            ]
        )

        largest_accounts = []

        if largest_result:

            largest_accounts = (
                largest_result.get(
                    "value",
                    []
                )
            )

        # =====================================================
        # 4. HOLDER INTELLIGENCE
        # =====================================================

        try:

            supply_number = int(
                supply
            )

        except Exception:

            supply_number = 0

        top_10_percentage = 0

        holder_wallets = {}

        liquidity_wallets = {}

        if supply_number > 0:

            for holder in largest_accounts[:10]:

                token_account = holder.get(
                    "address"
                )

                amount = int(
                    holder.get(
                        "amount",
                        0
                    )
                )

                percentage = (
                    amount / supply_number
                ) * 100

                top_10_percentage += percentage

                owner = None

                try:

                    owner = (
                        get_token_account_owner(
                            token_account
                        )
                    )

                except Exception as owner_error:

                    print(
                        "ERRO OWNER:",
                        repr(owner_error)
                    )

                if not owner:
                    continue

                if is_liquidity_pool_wallet(
                    owner,
                    pair_address
                ):

                    liquidity_wallets[
                        owner
                    ] = (
                        liquidity_wallets.get(
                            owner,
                            0
                        )
                        + percentage
                    )

                else:

                    holder_wallets[
                        owner
                    ] = (
                        holder_wallets.get(
                            owner,
                            0
                        )
                        + percentage
                    )

        pool_percentage = sum(
            liquidity_wallets.values()
        )

        real_holder_percentage = sum(
            holder_wallets.values()
        )

        unique_wallets = len(
            holder_wallets
        )

        sorted_wallets = sorted(
            holder_wallets.items(),
            key=lambda item: item[1],
            reverse=True
        )

        top_wallets_message = ""

        if sorted_wallets:

            for index, wallet in enumerate(
                sorted_wallets[:5],
                start=1
            ):

                top_wallets_message += (
                    f"{index}. "
                    f"`{wallet[0]}`\n"
                    f"   {wallet[1]:.2f}%\n"
                )

        else:

            top_wallets_message = (
                "Não foi possível identificar "
                "holders reais."
            )

        if liquidity_wallets:

            pool_message = (
                "💧 POOL IDENTIFICADA\n\n"
            )

            for pool, percentage in (
                liquidity_wallets.items()
            ):

                pool_message += (
                    f"Pool: `{pool}`\n"
                    f"Tokens na pool: "
                    f"{percentage:.2f}%\n\n"
                )

        else:

            pool_message = (
                "💧 POOL IDENTIFICADA\n\n"
                "Não foi possível confirmar a pool "
                "entre as maiores contas analisadas.\n\n"
            )

        if top_10_percentage >= 70:

            raw_concentration_status = (
                "🔴 MUITO ALTA"
            )

        elif top_10_percentage >= 50:

            raw_concentration_status = (
                "🟠 ALTA"
            )

        elif top_10_percentage >= 30:

            raw_concentration_status = (
                "🟡 MODERADA"
            )

        else:

            raw_concentration_status = (
                "🟢 BAIXA"
            )

        if real_holder_percentage >= 70:

            real_concentration_status = (
                "🔴 MUITO ALTA"
            )

        elif real_holder_percentage >= 50:

            real_concentration_status = (
                "🟠 ALTA"
            )

        elif real_holder_percentage >= 30:

            real_concentration_status = (
                "🟡 MODERADA"
            )

        else:

            real_concentration_status = (
                "🟢 BAIXA"
            )

        # =====================================================
        # 5. LIQUIDEZ STATUS
        # =====================================================

        if liquidity >= 50000:

            liquidity_status = "🟢 BOA"

        elif liquidity >= 15000:

            liquidity_status = "🟡 MODERADA"

        elif liquidity >= 5000:

            liquidity_status = "🟠 BAIXA"

        else:

            liquidity_status = "🔴 MUITO BAIXA"

        # =====================================================
        # 6. DEV WALLET INTELLIGENCE
        # =====================================================

        dev_data = {
            "wallet": None,
            "signature": None,
            "block_time": None,
            "signers": [],
            "confidence": "BAIXA",
            "reason": "Não analisado."
        }

        dev_activity = {
            "total": 0,
            "successful": 0,
            "failed": 0,
            "first_seen": None,
            "last_seen": None
        }

        try:

            dev_data = identify_deployer(
                token_address
            )

            dev_wallet = dev_data.get(
                "wallet"
            )

            if dev_wallet:

                dev_activity = (
                    get_wallet_activity(
                        dev_wallet,
                        limit=20
                    )
                )

        except Exception as dev_error:

            print(
                "ERRO DEV INTELLIGENCE:",
                repr(dev_error)
            )

        # =====================================================
        # 7. MENSAGEM DA DEV WALLET
        # =====================================================

        if dev_data.get("wallet"):

            dev_wallet = dev_data[
                "wallet"
            ]

            dev_signature = dev_data.get(
                "signature"
            )

            dev_block_time = dev_data.get(
                "block_time"
            )

            dev_confidence = dev_data.get(
                "confidence",
                "BAIXA"
            )

            signers = dev_data.get(
                "signers",
                []
            )

            dev_message = (
                "🧠 DEV WALLET INTELLIGENCE\n\n"

                "🟡 CANDIDATO A DEPLOYER\n\n"

                f"Wallet:\n"
                f"`{dev_wallet}`\n\n"

                f"Confiança da identificação: "
                f"{dev_confidence}\n\n"

                f"Primeira atividade analisada:\n"
                f"{format_timestamp(dev_block_time)}\n\n"

                f"Signatários encontrados: "
                f"{len(signers)}\n\n"

                f"Transação analisada:\n"
                f"`{dev_signature}`\n\n"

                "📜 HISTÓRICO RECENTE\n\n"

                f"Transações analisadas: "
                f"{dev_activity['total']}\n"

                f"Sucesso: "
                f"{dev_activity['successful']}\n"

                f"Falhas: "
                f"{dev_activity['failed']}\n\n"

                f"Primeira atividade no histórico "
                f"consultado:\n"
                f"{format_timestamp(dev_activity['first_seen'])}\n\n"

                f"Última atividade:\n"
                f"{format_timestamp(dev_activity['last_seen'])}\n\n"

                "⚠️ Essa wallet é um candidato "
                "a deployer baseado na atividade "
                "on-chain analisada.\n"

                "Isso não prova a identidade do "
                "desenvolvedor."
            )

        else:

            dev_message = (
                "🧠 DEV WALLET INTELLIGENCE\n\n"

                "⚪ NÃO IDENTIFICADA\n\n"

                "Não foi possível identificar "
                "um candidato confiável a deployer "
                "com os dados RPC consultados."
            )

        # =====================================================
        # 8. RESPOSTA FINAL
        # =====================================================

        message = (
            "🛡️ SECURITY ENGINE\n\n"

            f"🪙 Token:\n"
            f"`{token_address}`\n\n"

            "🔐 MINT AUTHORITY\n"
            f"{mint_status}\n\n"

            "🧊 FREEZE AUTHORITY\n"
            f"{freeze_status}\n\n"

            "🪙 SUPPLY\n"
            f"{supply}\n\n"

            "🔢 DECIMAIS\n"
            f"{decimals}\n\n"

            "⚙️ TOKEN PROGRAM\n"
            f"`{owner_program}`\n\n"

            "👥 HOLDER INTELLIGENCE\n\n"

            f"Token accounts analisadas: "
            f"{len(largest_accounts)}\n"

            f"Top 10 bruto: "
            f"{top_10_percentage:.2f}%\n"

            f"Concentração bruta: "
            f"{raw_concentration_status}\n\n"

            f"Owners reais identificados: "
            f"{unique_wallets}\n"

            f"Concentração real: "
            f"{real_holder_percentage:.2f}%\n"

            f"Status real: "
            f"{real_concentration_status}\n\n"

            f"{pool_message}"

            "👛 PRINCIPAIS HOLDERS REAIS\n\n"

            f"{top_wallets_message}\n"

            "💧 LIQUIDEZ\n"

            f"Liquidez: "
            f"${liquidity:,.0f}\n"

            f"Market Cap: "
            f"${market_cap:,.0f}\n"

            f"Volume 24h: "
            f"${volume_24h:,.0f}\n"

            f"Variação 24h: "
            f"{price_change:.2f}%\n\n"

            f"Liquidez: "
            f"{liquidity_status}\n"

            f"DEX: {dex_id}\n"

            f"Pool: `{pair_address}`\n\n"

            f"{dev_message}\n\n"

            "📊 PRÓXIMAS ANÁLISES\n\n"

            "• Histórico detalhado do dev\n"
            "• Tokens movimentados pelo dev\n"
            "• Transferências para outras wallets\n"
            "• Relação entre carteiras\n"
            "• Comportamento da liquidez\n"
            "• Risco de rug pull\n\n"

            "⚠️ Ainda não é um Security Score."
        )

        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )

    except Exception as error:

        print(
            "ERRO SECURITY:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ Erro dentro do Security Engine.\n\n"
            f"Detalhes: {error}"
        )


# =========================================================
# INICIALIZAÇÃO DO BOT
# =========================================================

def main():

    application = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "top",
            top
        )
    )

    application.add_handler(
        CommandHandler(
            "security",
            security
        )
    )

    print(
        "🤖 Meme Radar AI iniciado."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
