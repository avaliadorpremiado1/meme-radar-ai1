import os
import requests
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SOLANA_RPC = os.getenv("SOLANA_RPC")

TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


# ============================================================
# SOLANA RPC
# ============================================================

def solana_rpc(method, params):
    response = requests.post(
        SOLANA_RPC,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(data["error"])

    return data.get("result")


# ============================================================
# DEXSCREENER
# ============================================================

def get_liquidity_data(token_address):
    response = requests.get(
        f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
        timeout=20
    )

    response.raise_for_status()

    pairs = response.json().get("pairs") or []

    pairs = [
        pair
        for pair in pairs
        if pair.get("chainId") == "solana"
    ]

    if not pairs:
        return None

    return max(
        pairs,
        key=lambda pair: float(
            (pair.get("liquidity") or {}).get("usd") or 0
        )
    )


# ============================================================
# HELPERS
# ============================================================

def format_timestamp(timestamp):
    if not timestamp:
        return "N/D"

    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc
    ).strftime("%d/%m/%Y %H:%M UTC")


def get_token_account_owner(token_account):
    result = solana_rpc(
        "getAccountInfo",
        [
            token_account,
            {
                "encoding": "jsonParsed"
            }
        ]
    )

    try:
        return result["value"]["data"]["parsed"]["info"]["owner"]
    except (TypeError, KeyError):
        return None


def is_liquidity_pool_wallet(wallet_address, pair_address):
    if not wallet_address:
        return False

    if not pair_address:
        return False

    if pair_address == "N/D":
        return False

    return wallet_address == pair_address


# ============================================================
# TRANSACTIONS
# ============================================================

def get_mint_signatures(token_address, limit=100):
    return solana_rpc(
        "getSignaturesForAddress",
        [
            token_address,
            {
                "limit": min(limit, 100)
            }
        ]
    ) or []


def get_transaction(signature):
    return solana_rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    )


def get_account_keys(transaction):
    try:
        return transaction["transaction"]["message"]["accountKeys"]
    except (TypeError, KeyError):
        return []


def get_transaction_signers(transaction):
    signers = []

    for key in get_account_keys(transaction):

        if isinstance(key, dict) and key.get("signer"):

            pubkey = key.get("pubkey")

            if pubkey:
                signers.append(pubkey)

    return signers


def get_fee_payer(transaction):
    keys = get_account_keys(transaction)

    if not keys:
        return None

    first = keys[0]

    if isinstance(first, dict):
        return first.get("pubkey")

    return first


def extract_instructions(transaction):
    instructions = []

    try:
        message = transaction["transaction"]["message"]

        instructions.extend(
            message.get("instructions") or []
        )

        meta = transaction.get("meta") or {}

        for group in meta.get("innerInstructions") or []:
            instructions.extend(
                group.get("instructions") or []
            )

    except (TypeError, KeyError):
        pass

    return instructions


def get_instruction_program_id(instruction):
    if not isinstance(instruction, dict):
        return None

    if instruction.get("programId"):
        return instruction["programId"]

    program = instruction.get("program")

    if program in (
        "spl-token",
        "spl-token-2022",
        "system"
    ):
        return program

    return None


def get_instruction_accounts(instruction):
    if not isinstance(instruction, dict):
        return []

    accounts = instruction.get("accounts")

    if isinstance(accounts, list):
        return accounts

    return []


def get_transaction_logs(transaction):
    return (
        transaction.get("meta") or {}
    ).get("logMessages") or []


# ============================================================
# DEV WALLET INTELLIGENCE 3.1
# ============================================================

def inspect_mint_initialization(transaction, token_address):
    findings = []
    raw_token_instructions = []

    for instruction in extract_instructions(transaction):

        parsed = (
            instruction.get("parsed")
            if isinstance(instruction, dict)
            else None
        )

        # ----------------------------------------------------
        # Parsed instructions
        # ----------------------------------------------------

        if isinstance(parsed, dict):

            instruction_type = parsed.get("type")

            info = parsed.get("info") or {}

            if instruction_type in (
                "initializeMint",
                "initializeMint2"
            ):

                mint = info.get("mint")

                if mint == token_address:

                    findings.append({
                        "type": instruction_type,
                        "mint": mint,
                        "program": get_instruction_program_id(
                            instruction
                        ),
                        "parsed": True
                    })

            if instruction_type == "createAccount":

                new_account = info.get("newAccount")
                owner = info.get("owner")

                if (
                    new_account == token_address
                    and owner in (
                        TOKEN_PROGRAM_ID,
                        TOKEN_2022_PROGRAM_ID
                    )
                ):

                    findings.append({
                        "type": "createAccount",
                        "mint": token_address,
                        "program": SYSTEM_PROGRAM_ID,
                        "parsed": True
                    })

        # ----------------------------------------------------
        # Instruções parcialmente decodificadas
        # ----------------------------------------------------

        program_id = get_instruction_program_id(
            instruction
        )

        if program_id in (
            TOKEN_PROGRAM_ID,
            TOKEN_2022_PROGRAM_ID
        ):

            accounts = get_instruction_accounts(
                instruction
            )

            if (
                token_address in accounts
                and not parsed
            ):

                raw_token_instructions.append({
                    "program": program_id,
                    "accounts": accounts,
                    "data": instruction.get("data")
                })

    return findings, raw_token_instructions


def inspect_create_account(transaction, token_address):
    findings = []

    for instruction in extract_instructions(transaction):

        parsed = (
            instruction.get("parsed")
            if isinstance(instruction, dict)
            else None
        )

        if not isinstance(parsed, dict):
            continue

        if parsed.get("type") != "createAccount":
            continue

        info = parsed.get("info") or {}

        new_account = info.get("newAccount")
        owner = info.get("owner")

        if (
            new_account == token_address
            and owner in (
                TOKEN_PROGRAM_ID,
                TOKEN_2022_PROGRAM_ID
            )
        ):

            findings.append(info)

    return findings


def analyze_creation_transaction(
    transaction,
    token_address
):

    mint_findings, raw_token_instructions = (
        inspect_mint_initialization(
            transaction,
            token_address
        )
    )

    create_findings = inspect_create_account(
        transaction,
        token_address
    )

    signers = get_transaction_signers(
        transaction
    )

    fee_payer = get_fee_payer(
        transaction
    )

    mint_authority = False
    freeze_authority = False

    for instruction in extract_instructions(transaction):

        parsed = (
            instruction.get("parsed")
            if isinstance(instruction, dict)
            else None
        )

        if not isinstance(parsed, dict):
            continue

        if parsed.get("type") not in (
            "initializeMint",
            "initializeMint2"
        ):
            continue

        info = parsed.get("info") or {}

        if info.get("mint") != token_address:
            continue

        if info.get("mintAuthority") in signers:
            mint_authority = True

        if info.get("freezeAuthority") in signers:
            freeze_authority = True

    return {
        "mint_findings": mint_findings,
        "raw_token_instructions": raw_token_instructions,
        "create_findings": create_findings,
        "signers": signers,
        "fee_payer": fee_payer,
        "mint_authority": mint_authority,
        "freeze_authority": freeze_authority,
        "logs": get_transaction_logs(transaction)
    }


# ============================================================
# CANDIDATE STRUCTURE
# ============================================================

def new_candidate_record(wallet):

    return {
        "wallet": wallet,
        "score": 0,
        "evidence": [],
        "first_signature": None,
        "first_block_time": None,
        "fee_payer": False,
        "signer": False,
        "mint_authority": False,
        "freeze_authority": False,
        "initialize_mint": False,
        "create_account": False
    }


def add_evidence(
    candidate,
    points,
    label
):

    candidate["score"] += points

    if label not in candidate["evidence"]:
        candidate["evidence"].append(label)


def identify_deployer_candidates(
    token_address,
    limit=100
):

    signatures = get_mint_signatures(
        token_address,
        limit
    )

    successful = [
        signature
        for signature in signatures
        if not signature.get("err")
    ]

    successful.reverse()

    candidates = {}

    for signature_info in successful:

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        try:
            transaction = get_transaction(
                signature
            )
        except Exception:
            continue

        if not transaction:
            continue

        analysis = analyze_creation_transaction(
            transaction,
            token_address
        )

        creation_evidence = (
            analysis["mint_findings"]
            or analysis["create_findings"]
            or analysis["raw_token_instructions"]
        )

        if not creation_evidence:
            continue

        wallets = set(
            analysis["signers"]
        )

        if analysis["fee_payer"]:
            wallets.add(
                analysis["fee_payer"]
            )

        for wallet in wallets:

            if wallet not in candidates:

                candidates[wallet] = (
                    new_candidate_record(
                        wallet
                    )
                )

            candidate = candidates[wallet]

            candidate["first_signature"] = (
                signature
            )

            candidate["first_block_time"] = (
                signature_info.get(
                    "blockTime"
                )
            )

            if wallet == analysis["fee_payer"]:

                if not candidate["fee_payer"]:

                    add_evidence(
                        candidate,
                        20,
                        "fee payer da transação de criação"
                    )

                    candidate["fee_payer"] = True

            if wallet in analysis["signers"]:

                if not candidate["signer"]:

                    add_evidence(
                        candidate,
                        15,
                        "assinante da transação"
                    )

                    candidate["signer"] = True

            if (
                analysis["mint_authority"]
                and wallet in analysis["signers"]
            ):

                if not candidate["mint_authority"]:

                    add_evidence(
                        candidate,
                        35,
                        "associado à mint authority"
                    )

                    candidate["mint_authority"] = True

            if (
                analysis["freeze_authority"]
                and wallet in analysis["signers"]
            ):

                if not candidate["freeze_authority"]:

                    add_evidence(
                        candidate,
                        15,
                        "associado à freeze authority"
                    )

                    candidate["freeze_authority"] = True

            if analysis["mint_findings"]:

                if not candidate["initialize_mint"]:

                    add_evidence(
                        candidate,
                        15,
                        "initializeMint/initializeMint2 detectado"
                    )

                    candidate["initialize_mint"] = True

            if analysis["create_findings"]:

                if not candidate["create_account"]:

                    add_evidence(
                        candidate,
                        10,
                        "CreateAccount do mint detectado"
                    )

                    candidate["create_account"] = True

    results = []

    for candidate in candidates.values():

        candidate["score"] = min(
            candidate["score"],
            100
        )

        if candidate["score"] >= 70:
            candidate["confidence"] = "FORTE"

        elif candidate["score"] >= 40:
            candidate["confidence"] = "MÉDIA"

        elif candidate["score"] >= 20:
            candidate["confidence"] = "BAIXA"

        else:
            candidate["confidence"] = "MUITO BAIXA"

        results.append(candidate)

    results.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    return results, len(signatures)


# ============================================================
# HOLDER INTELLIGENCE + POOL INTELLIGENCE
# ============================================================

def holder_intelligence(
    token_address,
    pair_address=None
):

    largest = solana_rpc(
        "getTokenLargestAccounts",
        [token_address]
    ) or {}

    accounts = largest.get("value") or []

    supply_raw = 0

    try:

        supply = solana_rpc(
            "getTokenSupply",
            [token_address]
        )

        supply_raw = float(
            supply["value"]["amount"]
        )

    except Exception:
        pass

    owners = {}

    # Quantidade de tokens pertencentes à pool
    pool_amount = 0

    # Token accounts que foram identificadas
    pool_accounts_found = []

    for account in accounts[:20]:

        token_account_address = account.get(
            "address"
        )

        amount = float(
            account.get("amount") or 0
        )

        owner = get_token_account_owner(
            token_account_address
        )

        # ----------------------------------------------------
        # HOLDER REAL
        # ----------------------------------------------------

        if owner:

            owners[owner] = (
                owners.get(owner, 0)
                + amount
            )

        # ----------------------------------------------------
        # POOL INTELLIGENCE CORRIGIDO
        # ----------------------------------------------------
        #
        # Antes o bot fazia somente:
        #
        # token_account_address == pair_address
        #
        # Isso pode resultar em 0%.
        #
        # Agora verificamos:
        #
        # 1. endereço da token account
        # 2. owner da token account
        #
        # Assim conseguimos identificar quando a pool
        # controla uma token account específica.
        # ----------------------------------------------------

        if pair_address:

            is_pool_account = (
                token_account_address
                == pair_address
            )

            is_pool_owner = (
                owner == pair_address
            )

            if (
                is_pool_account
                or is_pool_owner
            ):

                pool_amount += amount

                pool_accounts_found.append({
                    "token_account": token_account_address,
                    "owner": owner,
                    "amount": amount
                })

    top10_raw = sum(
        float(account.get("amount") or 0)
        for account in accounts[:10]
    )

    real_top = sorted(
        owners.items(),
        key=lambda item: item[1],
        reverse=True
    )

    real_top10 = sum(
        amount
        for _, amount in real_top[:10]
    )

    denominator = supply_raw or 1

    return {
        "accounts_analyzed": len(
            accounts[:20]
        ),
        "top10_raw_pct": (
            top10_raw
            / denominator
            * 100
        ),
        "real_concentration_pct": (
            real_top10
            / denominator
            * 100
        ),
        "owners_identified": len(owners),
        "pool_pct": (
            pool_amount
            / denominator
            * 100
        ),
        "pool_amount": pool_amount,
        "pool_accounts_found": pool_accounts_found,
        "top_owners": [
            (
                wallet,
                amount
                / denominator
                * 100
            )
            for wallet, amount
            in real_top[:5]
        ]
    }


# ============================================================
# WALLET TOKEN DATA
# ============================================================

def get_wallet_token_accounts(
    wallet_address,
    mint
):

    result = solana_rpc(
        "getTokenAccountsByOwner",
        [
            wallet_address,
            {
                "mint": mint
            },
            {
                "encoding": "jsonParsed"
            }
        ]
    )

    if not result:
        return []

    return result.get(
        "value",
        []
    )


def get_wallet_token_balance(
    wallet_address,
    mint
):

    total = 0

    accounts = get_wallet_token_accounts(
        wallet_address,
        mint
    )

    for account in accounts:

        try:

            amount = float(
                account["account"]
                ["data"]
                ["parsed"]
                ["info"]
                ["tokenAmount"]
                ["amount"]
            )

            total += amount

        except (
            KeyError,
            TypeError,
            ValueError
        ):
            pass

    return total


def get_token_balance_map(
    transaction,
    token_address
):

    balances = {}

    meta = transaction.get(
        "meta"
    ) or {}

    for key in (
        "preTokenBalances",
        "postTokenBalances"
    ):

        for item in (
            meta.get(key) or []
        ):

            if item.get("mint") != token_address:
                continue

            owner = item.get("owner")

            if not owner:
                continue

            if owner not in balances:
                balances[owner] = {}

            balances[owner][key] = int(
                (
                    item.get(
                        "uiTokenAmount"
                    ) or {}
                ).get(
                    "amount"
                ) or 0
            )

    return balances


# ============================================================
# DEV TOKEN MOVEMENTS
# ============================================================

def analyze_dev_token_movements(
    wallet_address,
    token_address,
    signatures
):

    received = 0
    sent = 0
    tx_count = 0

    for signature_info in signatures[:30]:

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        try:

            transaction = get_transaction(
                signature
            )

        except Exception:
            continue

        if not transaction:
            continue

        balances = get_token_balance_map(
            transaction,
            token_address
        )

        entry = balances.get(
            wallet_address
        )

        if not entry:
            continue

        pre = entry.get(
            "preTokenBalances",
            0
        )

        post = entry.get(
            "postTokenBalances",
            0
        )

        delta = post - pre

        if delta > 0:
            received += delta

        elif delta < 0:
            sent += abs(delta)

        tx_count += 1

    return {
        "received": received,
        "sent": sent,
        "transactions": tx_count
    }


# ============================================================
# POSSIBLE FUNDERS
# ============================================================

def analyze_possible_funders(
    wallet_address,
    token_address,
    signatures
):

    funders = {}

    for signature_info in signatures[:30]:

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        try:

            transaction = get_transaction(
                signature
            )

        except Exception:
            continue

        if not transaction:
            continue

        balances = get_token_balance_map(
            transaction,
            token_address
        )

        dev = balances.get(
            wallet_address
        )

        if not dev:
            continue

        dev_pre = dev.get(
            "preTokenBalances",
            0
        )

        dev_post = dev.get(
            "postTokenBalances",
            0
        )

        if dev_post <= dev_pre:
            continue

        dev_increase = (
            dev_post - dev_pre
        )

        for other_wallet, values in balances.items():

            if other_wallet == wallet_address:
                continue

            other_pre = values.get(
                "preTokenBalances",
                0
            )

            other_post = values.get(
                "postTokenBalances",
                0
            )

            if other_post < other_pre:

                decrease = (
                    other_pre - other_post
                )

                funders[other_wallet] = (
                    funders.get(
                        other_wallet,
                        0
                    )
                    + min(
                        decrease,
                        dev_increase
                    )
                )

    return sorted(
        funders.items(),
        key=lambda item: item[1],
        reverse=True
    )[:5]


# ============================================================
# DEV BEHAVIOR
# ============================================================

def classify_dev_behavior(
    movements,
    funders
):

    score = 0
    notes = []

    if movements["transactions"] > 0:

        score += 20

        notes.append(
            "wallet possui atividade relacionada ao token"
        )

    if movements["received"] > 0:

        score += 20

        notes.append(
            "houve recebimento do token"
        )

    if (
        movements["sent"]
        > movements["received"]
        and movements["sent"] > 0
    ):

        score += 30

        notes.append(
            "houve saída de tokens superior às entradas observadas"
        )

    if funders:

        score += 10

        notes.append(
            "há possíveis fontes de distribuição identificadas"
        )

    return min(score, 100), notes


# ============================================================
# BASIC SECURITY
# ============================================================

def basic_security(token_address):

    info = solana_rpc(
        "getAccountInfo",
        [
            token_address,
            {
                "encoding": "jsonParsed"
            }
        ]
    )

    value = (
        info or {}
    ).get("value")

    if not value:
        raise ValueError(
            "Token não encontrado na Solana."
        )

    parsed = (
        value.get("data", {})
        .get("parsed", {})
    )

    mint_info = parsed.get(
        "info",
        {}
    )

    return {
        "mint_authority": mint_info.get(
            "mintAuthority"
        ),
        "freeze_authority": mint_info.get(
            "freezeAuthority"
        ),
        "supply": mint_info.get(
            "supply",
            "N/D"
        ),
        "decimals": mint_info.get(
            "decimals",
            "N/D"
        ),
        "program": value.get(
            "owner",
            "N/D"
        )
    }


# ============================================================
# MARKET SCORE
# ============================================================

def market_score(pair):

    liquidity = float(
        (
            pair.get("liquidity")
            or {}
        ).get("usd")
        or 0
    )

    volume = float(
        (
            pair.get("volume")
            or {}
        ).get("h24")
        or 0
    )

    change = float(
        (
            pair.get("priceChange")
            or {}
        ).get("h24")
        or 0
    )

    score = min(
        liquidity / 50000 * 30,
        30
    )

    score += min(
        volume / 1000000 * 30,
        30
    )

    if change >= 50:

        score += 5

    else:

        score += min(
            max(change, 0) / 50 * 20,
            20
        )

    if liquidity:

        score += min(
            volume / liquidity * 10,
            20
        )

    return round(score)


# ============================================================
# TELEGRAM
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🤖 Meme Radar AI\n\n"
        "/top - melhores oportunidades de mercado\n"
        "/security TOKEN - análise de segurança\n"
        "/help - ajuda"
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "/top\n"
        "Mostra tokens Solana com maior atividade de mercado.\n\n"
        "/security ENDERECO\n"
        "Executa a análise de segurança, holders, pool e Dev Wallet."
    )


# ============================================================
# /TOP
# ============================================================

async def top(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        response = requests.get(
            "https://api.dexscreener.com/token-profiles/latest/v1",
            timeout=20
        )

        profiles = response.json()

        tokens = []

        for item in profiles[:100]:

            if item.get("chainId") != "solana":
                continue

            address = item.get(
                "tokenAddress"
            )

            if not address:
                continue

            try:

                pair = get_liquidity_data(
                    address
                )

            except Exception:

                continue

            if not pair:
                continue

            liquidity = float(
                (
                    pair.get("liquidity")
                    or {}
                ).get("usd")
                or 0
            )

            volume = float(
                (
                    pair.get("volume")
                    or {}
                ).get("h24")
                or 0
            )

            if liquidity < 15000:
                continue

            if volume < 10000:
                continue

            score = market_score(
                pair
            )

            tokens.append(
                (
                    score,
                    pair
                )
            )

        tokens.sort(
            key=lambda item: item[0],
            reverse=True
        )

        lines = [
            "📊 TOP MARKET RADAR\n"
        ]

        for index, (
            score,
            pair
        ) in enumerate(
            tokens[:5],
            1
        ):

            base = (
                pair.get("baseToken")
                or {}
            )

            liquidity = float(
                (
                    pair.get("liquidity")
                    or {}
                ).get("usd")
                or 0
            )

            volume = float(
                (
                    pair.get("volume")
                    or {}
                ).get("h24")
                or 0
            )

            change = float(
                (
                    pair.get("priceChange")
                    or {}
                ).get("h24")
                or 0
            )

            market_cap = float(
                pair.get("marketCap")
                or 0
            )

            lines.append(
                f"{index}. "
                f"{base.get('name', 'N/D')} "
                f"({base.get('symbol', 'N/D')})\n"
                f"Score mercado: {score}\n"
                f"Liquidez: ${liquidity:,.0f}\n"
                f"Volume 24h: ${volume:,.0f}\n"
                f"Variação 24h: {change:.2f}%\n"
                f"MC: ${market_cap:,.0f}\n"
                f"Token: {base.get('address')}\n"
            )

        lines.append(
            "⚠️ Ranking de mercado. "
            "Ainda não representa sinal de compra."
        )

        await update.message.reply_text(
            "\n".join(lines)
        )

    except Exception as error:

        await update.message.reply_text(
            f"❌ Erro no /top: {error}"
        )


# ============================================================
# /SECURITY
# ============================================================

async def security(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use: /security ENDERECO_DO_TOKEN"
        )

        return

    token = context.args[0]

    try:

        # ----------------------------------------------------
        # BASIC SECURITY
        # ----------------------------------------------------

        security_data = basic_security(
            token
        )

        # ----------------------------------------------------
        # POOL
        # ----------------------------------------------------

        pair = get_liquidity_data(
            token
        )

        pair_address = (
            pair.get("pairAddress")
            if pair
            else None
        )

        # ----------------------------------------------------
        # HOLDERS + POOL
        # ----------------------------------------------------

        holders = holder_intelligence(
            token,
            pair_address
        )

        # ----------------------------------------------------
        # DEV WALLET 3.1
        # ----------------------------------------------------

        candidates, tx_count = (
            identify_deployer_candidates(
                token,
                100
            )
        )

        # ----------------------------------------------------
        # MESSAGE
        # ----------------------------------------------------

        text = [
            "🛡️ SECURITY ENGINE\n",
            f"🪙 Token:\n{token}\n",

            "🔐 MINT AUTHORITY"
        ]

        if not security_data["mint_authority"]:

            text.append(
                "✅ REVOGADA"
            )

        else:

            text.append(
                "⚠️ ATIVA: "
                + str(
                    security_data[
                        "mint_authority"
                    ]
                )
            )

        text.extend([
            "\n🧊 FREEZE AUTHORITY"
        ])

        if not security_data["freeze_authority"]:

            text.append(
                "✅ REVOGADA"
            )

        else:

            text.append(
                "⚠️ ATIVA: "
                + str(
                    security_data[
                        "freeze_authority"
                    ]
                )
            )

        text.extend([
            f"\n🪙 SUPPLY\n"
            f"{security_data['supply']}",

            f"\n🔢 DECIMAIS\n"
            f"{security_data['decimals']}",

            f"\n⚙️ TOKEN PROGRAM\n"
            f"{security_data['program']}",

            "\n👥 HOLDER INTELLIGENCE",

            f"\nToken accounts analisadas: "
            f"{holders['accounts_analyzed']}",

            f"Top 10 bruto: "
            f"{holders['top10_raw_pct']:.2f}%",

            f"Owners reais identificados: "
            f"{holders['owners_identified']}",

            f"Concentração real: "
            f"{holders['real_concentration_pct']:.2f}%",

            f"\n💧 POOL IDENTIFICADA",

            f"\nPool: "
            f"{pair_address or 'N/D'}",

            f"Tokens na pool: "
            f"{holders['pool_pct']:.2f}%"
        ])

        # ----------------------------------------------------
        # POOL DATA
        # ----------------------------------------------------

        if pair:

            liquidity = float(
                (
                    pair.get("liquidity")
                    or {}
                ).get("usd")
                or 0
            )

            market_cap = float(
                pair.get("marketCap")
                or 0
            )

            volume = float(
                (
                    pair.get("volume")
                    or {}
                ).get("h24")
                or 0
            )

            change = float(
                (
                    pair.get("priceChange")
                    or {}
                ).get("h24")
                or 0
            )

            text.extend([

                "\n💧 LIQUIDEZ",

                f"Liquidez: "
                f"${liquidity:,.0f}",

                f"Market Cap: "
                f"${market_cap:,.0f}",

                f"Volume 24h: "
                f"${volume:,.0f}",

                f"Variação 24h: "
                f"{change:.2f}%",

                f"DEX: "
                f"{pair.get('dexId', 'N/D')}"
            ])

        # ----------------------------------------------------
        # DEV WALLET
        # ----------------------------------------------------

        text.extend([

            "\n🧠 DEV WALLET INTELLIGENCE 3.1",

            f"\n🔎 Transações do mint analisadas: "
            f"{tx_count}"
        ])

        if not candidates:

            text.extend([

                "\n⚪ DEPLOYER NÃO IDENTIFICADO",

                "\nNenhuma evidência de criação suficiente "
                "foi encontrada nas transações analisadas.",

                "\nIsso é diferente de afirmar que não "
                "existe deployer identificável; apenas "
                "não houve evidência suficiente."
            ])

        else:

            text.append(
                "\n👛 CANDIDATOS A DEPLOYER"
            )

            for index, candidate in enumerate(
                candidates[:3],
                1
            ):

                evidence = ", ".join(
                    candidate["evidence"]
                )

                text.extend([

                    f"\n{index}. "
                    f"{candidate['wallet']}",

                    f"Score de evidência: "
                    f"{candidate['score']}/100",

                    f"Confiança: "
                    f"{candidate['confidence']}",

                    f"Evidências: "
                    f"{evidence}",

                    f"Primeira evidência: "
                    f"{format_timestamp(candidate['first_block_time'])}",

                    f"Tx: "
                    f"{candidate['first_signature'] or 'N/D'}"
                ])

        text.extend([

            "\n⚠️ IMPORTANTE",

            "A análise identifica candidatos "
            "com base em evidências on-chain.",

            "Isso não prova a identidade real "
            "do desenvolvedor.",

            "\n📊 PRÓXIMAS ANÁLISES",

            "• Histórico on-chain completo",
            "• Relação entre wallets",
            "• Funding em cadeia",
            "• Comportamento da liquidez",
            "• Distribuição coordenada",
            "• Risco de rug pull",

            "\n⚠️ Ainda não é um Security Score."
        ])

        await update.message.reply_text(
            "\n".join(text)
        )

    except Exception as error:

        await update.message.reply_text(
            f"❌ Erro no /security: {error}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_TOKEN:

        raise RuntimeError(
            "TELEGRAM_TOKEN não configurado."
        )

    if not SOLANA_RPC:

        raise RuntimeError(
            "SOLANA_RPC não configurado."
        )

    app = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "top",
            top
        )
    )

    app.add_handler(
        CommandHandler(
            "security",
            security
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
