import os
import requests
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


# =========================================================
# CONFIGURAÇÃO
# =========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SOLANA_RPC = os.getenv("SOLANA_RPC")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado.")

if not SOLANA_RPC:
    raise RuntimeError("SOLANA_RPC não configurado.")


# =========================================================
# SOLANA RPC
# =========================================================

def solana_rpc(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or []
    }

    try:
        response = requests.post(
            SOLANA_RPC,
            json=payload,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            print("RPC ERROR:", data["error"])
            return None

        return data.get("result")

    except Exception as e:
        print("RPC EXCEPTION:", e)
        return None


# =========================================================
# DEXSCREENER / LIQUIDEZ
# =========================================================

def get_liquidity_data(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"

        response = requests.get(
            url,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

        pairs = data.get("pairs") or []

        solana_pairs = [
            pair
            for pair in pairs
            if pair.get("chainId") == "solana"
        ]

        if not solana_pairs:
            return None

        solana_pairs.sort(
            key=lambda x: float(
                (x.get("liquidity") or {}).get("usd") or 0
            ),
            reverse=True
        )

        pair = solana_pairs[0]

        liquidity = float(
            (pair.get("liquidity") or {}).get("usd") or 0
        )

        market_cap = float(
            pair.get("marketCap") or
            pair.get("fdv") or
            0
        )

        volume_24h = float(
            (pair.get("volume") or {}).get("h24") or 0
        )

        price_change_24h = float(
            (pair.get("priceChange") or {}).get("h24") or 0
        )

        return {
            "liquidity": liquidity,
            "market_cap": market_cap,
            "volume_24h": volume_24h,
            "price_change_24h": price_change_24h,
            "dex": pair.get("dexId") or "N/D",
            "pair_address": pair.get("pairAddress") or "N/D",
            "symbol": (pair.get("baseToken") or {}).get("symbol") or "N/D",
            "name": (pair.get("baseToken") or {}).get("name") or "N/D"
        }

    except Exception as e:
        print("DEXSCREENER ERROR:", e)
        return None


# =========================================================
# TOKEN ACCOUNT OWNER
# =========================================================

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

    if not result:
        return None

    value = result.get("value")

    if not value:
        return None

    data = value.get("data")

    if not isinstance(data, dict):
        return None

    parsed = data.get("parsed")

    if not isinstance(parsed, dict):
        return None

    info = parsed.get("info")

    if not isinstance(info, dict):
        return None

    return info.get("owner")


# =========================================================
# POOL INTELLIGENCE
# =========================================================

def is_liquidity_pool_wallet(wallet_address, pair_address):
    if not wallet_address:
        return False

    if not pair_address:
        return False

    if pair_address == "N/D":
        return False

    return wallet_address == pair_address


# =========================================================
# TIMESTAMP
# =========================================================

def format_timestamp(timestamp):
    if not timestamp:
        return "N/D"

    try:
        dt = datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc
        )

        return dt.strftime("%d/%m/%Y %H:%M UTC")

    except Exception:
        return "N/D"


# =========================================================
# ASSINATURAS DO MINT
# =========================================================

def get_mint_signatures(token_address, limit=100):
    result = solana_rpc(
        "getSignaturesForAddress",
        [
            token_address,
            {
                "limit": limit
            }
        ]
    )

    if not result:
        return []

    return result


# =========================================================
# TRANSAÇÃO
# =========================================================

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


# =========================================================
# ACCOUNT KEYS
# =========================================================

def get_account_keys(transaction):
    try:
        message = (
            transaction
            .get("transaction", {})
            .get("message", {})
        )

        account_keys = message.get("accountKeys") or []

        result = []

        for key in account_keys:

            if isinstance(key, dict):
                pubkey = key.get("pubkey")

                if pubkey:
                    result.append({
                        "pubkey": pubkey,
                        "signer": bool(key.get("signer")),
                        "writable": bool(key.get("writable"))
                    })

            elif isinstance(key, str):
                result.append({
                    "pubkey": key,
                    "signer": False,
                    "writable": False
                })

        return result

    except Exception:
        return []


# =========================================================
# SIGNERS
# =========================================================

def get_transaction_signers(transaction):
    keys = get_account_keys(transaction)

    return [
        item["pubkey"]
        for item in keys
        if item.get("signer")
    ]


# =========================================================
# FEE PAYER
# =========================================================

def get_fee_payer(transaction):
    keys = get_account_keys(transaction)

    if not keys:
        return None

    return keys[0].get("pubkey")


# =========================================================
# NORMALIZA INSTRUÇÕES
# =========================================================

def extract_instructions(transaction):
    instructions = []

    try:
        message = (
            transaction
            .get("transaction", {})
            .get("message", {})
        )

        top_level = message.get("instructions") or []

        for instruction in top_level:
            instructions.append({
                "instruction": instruction,
                "source": "top-level"
            })

        meta = transaction.get("meta") or {}

        inner_groups = meta.get("innerInstructions") or []

        for group in inner_groups:

            for instruction in group.get("instructions") or []:
                instructions.append({
                    "instruction": instruction,
                    "source": "inner"
                })

    except Exception as e:
        print("INSTRUCTION ERROR:", e)

    return instructions


# =========================================================
# DETECTA INITIALIZE MINT
# =========================================================

def inspect_mint_initialization(transaction, token_address):
    findings = []

    instructions = extract_instructions(transaction)

    for item in instructions:

        instruction = item["instruction"]

        if not isinstance(instruction, dict):
            continue

        parsed = instruction.get("parsed")

        if not isinstance(parsed, dict):
            continue

        instruction_type = parsed.get("type")

        if instruction_type not in [
            "initializeMint",
            "initializeMint2"
        ]:
            continue

        info = parsed.get("info") or {}

        mint = info.get("mint")

        if mint != token_address:
            continue

        program = instruction.get("program")
        program_id = instruction.get("programId")

        findings.append({
            "type": instruction_type,
            "source": item["source"],
            "program": program or "N/D",
            "program_id": program_id or "N/D",
            "info": info
        })

    return findings


# =========================================================
# EXTRAI EVIDÊNCIAS DO MINT
# =========================================================

def analyze_mint_initialization_transaction(
    transaction,
    token_address
):
    findings = inspect_mint_initialization(
        transaction,
        token_address
    )

    if not findings:
        return []

    fee_payer = get_fee_payer(transaction)
    signers = get_transaction_signers(transaction)

    evidence = []

    for finding in findings:

        info = finding.get("info") or {}

        mint_authority = info.get("mintAuthority")
        freeze_authority = info.get("freezeAuthority")

        candidate_wallets = set()

        if fee_payer:
            candidate_wallets.add(fee_payer)

        for signer in signers:
            candidate_wallets.add(signer)

        if mint_authority:
            candidate_wallets.add(mint_authority)

        if freeze_authority:
            candidate_wallets.add(freeze_authority)

        for wallet in candidate_wallets:

            evidence.append({
                "wallet": wallet,
                "fee_payer": wallet == fee_payer,
                "signer": wallet in signers,
                "mint_authority": wallet == mint_authority,
                "freeze_authority": wallet == freeze_authority,
                "initialize_type": finding.get("type"),
                "source": finding.get("source"),
                "program": finding.get("program"),
                "program_id": finding.get("program_id"),
                "signature": None
            })

    return evidence


# =========================================================
# DEV WALLET INTELLIGENCE 3.0
# =========================================================

def identify_deployer_candidates(token_address, max_signatures=100):

    signatures = get_mint_signatures(
        token_address,
        limit=max_signatures
    )

    if not signatures:
        return {
            "candidates": [],
            "initialization_found": False,
            "transactions_scanned": 0,
            "initialization_transactions": []
        }

    # getSignaturesForAddress retorna do mais novo
    # para o mais antigo.
    # Vamos inverter para procurar primeiro as mais antigas.
    ordered_signatures = list(reversed(signatures))

    candidate_map = {}

    initialization_transactions = []

    transactions_scanned = 0

    for signature_info in ordered_signatures:

        signature = signature_info.get("signature")

        if not signature:
            continue

        # Ignora transações explicitamente falhas
        if signature_info.get("err") is not None:
            continue

        transaction = get_transaction(signature)

        transactions_scanned += 1

        if not transaction:
            continue

        findings = inspect_mint_initialization(
            transaction,
            token_address
        )

        if not findings:
            continue

        fee_payer = get_fee_payer(transaction)

        signers = get_transaction_signers(transaction)

        initialization_transactions.append({
            "signature": signature,
            "slot": transaction.get("slot"),
            "block_time": transaction.get("blockTime"),
            "fee_payer": fee_payer,
            "signers": signers,
            "findings": findings
        })

        for finding in findings:

            info = finding.get("info") or {}

            mint_authority = info.get("mintAuthority")
            freeze_authority = info.get("freezeAuthority")

            wallets = set()

            if fee_payer:
                wallets.add(fee_payer)

            for signer in signers:
                wallets.add(signer)

            if mint_authority:
                wallets.add(mint_authority)

            if freeze_authority:
                wallets.add(freeze_authority)

            for wallet in wallets:

                if wallet not in candidate_map:
                    candidate_map[wallet] = {
                        "wallet": wallet,
                        "fee_payer_count": 0,
                        "signer_count": 0,
                        "mint_authority_count": 0,
                        "freeze_authority_count": 0,
                        "initialize_count": 0,
                        "initialize_mint_count": 0,
                        "initialize_mint2_count": 0,
                        "programs": set(),
                        "program_ids": set(),
                        "signatures": [],
                        "first_initialization": None
                    }

                candidate = candidate_map[wallet]

                if wallet == fee_payer:
                    candidate["fee_payer_count"] += 1

                if wallet in signers:
                    candidate["signer_count"] += 1

                if wallet == mint_authority:
                    candidate["mint_authority_count"] += 1

                if wallet == freeze_authority:
                    candidate["freeze_authority_count"] += 1

                candidate["initialize_count"] += 1

                if finding.get("type") == "initializeMint":
                    candidate["initialize_mint_count"] += 1

                if finding.get("type") == "initializeMint2":
                    candidate["initialize_mint2_count"] += 1

                program = finding.get("program")

                if program:
                    candidate["programs"].add(program)

                program_id = finding.get("program_id")

                if program_id:
                    candidate["program_ids"].add(program_id)

                if signature not in candidate["signatures"]:
                    candidate["signatures"].append(signature)

                block_time = transaction.get("blockTime")

                if (
                    candidate["first_initialization"] is None
                    or (
                        block_time is not None
                        and block_time < candidate["first_initialization"]
                    )
                ):
                    candidate["first_initialization"] = block_time

    # =====================================================
    # CALCULA SCORE DOS CANDIDATOS
    # =====================================================

    candidates = []

    for wallet, candidate in candidate_map.items():

        score = 0
        reasons = []

        # Evidência mais forte:
        # wallet aparece como mint authority
        if candidate["mint_authority_count"] > 0:
            score += 35
            reasons.append("Mint authority")

        # Freeze authority também é uma evidência
        if candidate["freeze_authority_count"] > 0:
            score += 15
            reasons.append("Freeze authority")

        # Foi quem pagou a transação de inicialização
        if candidate["fee_payer_count"] > 0:
            score += 20
            reasons.append("Fee payer")

        # Assinou a transação
        if candidate["signer_count"] > 0:
            score += 15
            reasons.append("Signer")

        # Apareceu diretamente em initializeMint
        if candidate["initialize_count"] > 0:
            score += 15
            reasons.append("Participou da inicialização")

        # Limita score
        score = min(score, 100)

        if score >= 70:
            confidence = "FORTE"
            status = "🟢 FORTE EVIDÊNCIA"

        elif score >= 40:
            confidence = "MÉDIA"
            status = "🟡 POSSÍVEL OPERADOR"

        elif score >= 20:
            confidence = "BAIXA"
            status = "⚪ BAIXA EVIDÊNCIA"

        else:
            confidence = "MUITO BAIXA"
            status = "⚪ EVIDÊNCIA INSUFICIENTE"

        candidates.append({
            "wallet": wallet,
            "score": score,
            "confidence": confidence,
            "status": status,
            "reasons": reasons,
            "fee_payer_count": candidate["fee_payer_count"],
            "signer_count": candidate["signer_count"],
            "mint_authority_count": candidate["mint_authority_count"],
            "freeze_authority_count": candidate["freeze_authority_count"],
            "initialize_count": candidate["initialize_count"],
            "initialize_mint_count": candidate["initialize_mint_count"],
            "initialize_mint2_count": candidate["initialize_mint2_count"],
            "programs": sorted(candidate["programs"]),
            "program_ids": sorted(candidate["program_ids"]),
            "signatures": candidate["signatures"],
            "first_initialization": candidate["first_initialization"]
        })

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return {
        "candidates": candidates,
        "initialization_found": len(initialization_transactions) > 0,
        "transactions_scanned": transactions_scanned,
        "initialization_transactions": initialization_transactions
    }


# =========================================================
# ATIVIDADE DA WALLET
# =========================================================

def get_wallet_activity(wallet_address, limit=30):

    signatures = solana_rpc(
        "getSignaturesForAddress",
        [
            wallet_address,
            {
                "limit": limit
            }
        ]
    )

    if not signatures:
        return []

    activity = []

    for signature_info in signatures:

        signature = signature_info.get("signature")

        if not signature:
            continue

        transaction = get_transaction(signature)

        if not transaction:
            continue

        activity.append({
            "signature": signature,
            "block_time": transaction.get("blockTime"),
            "slot": transaction.get("slot"),
            "success": signature_info.get("err") is None
        })

    return activity


# =========================================================
# TOKEN ACCOUNTS DA WALLET
# =========================================================

def get_wallet_token_accounts(wallet_address, token_address):

    result = solana_rpc(
        "getTokenAccountsByOwner",
        [
            wallet_address,
            {
                "mint": token_address
            },
            {
                "encoding": "jsonParsed"
            }
        ]
    )

    if not result:
        return []

    return result.get("value") or []


# =========================================================
# SALDO DO TOKEN NA WALLET
# =========================================================

def get_wallet_token_balance(wallet_address, token_address):

    accounts = get_wallet_token_accounts(
        wallet_address,
        token_address
    )

    total = 0.0

    for account in accounts:

        try:
            info = (
                account
                .get("account", {})
                .get("data", {})
                .get("parsed", {})
                .get("info", {})
            )

            token_amount = info.get("tokenAmount") or {}

            amount = float(
                token_amount.get("uiAmount") or 0
            )

            total += amount

        except Exception:
            continue

    return {
        "balance": total,
        "accounts": len(accounts)
    }


# =========================================================
# TOKEN BALANCE MAP
# =========================================================

def get_token_balance_map(transaction, token_address):

    result = {
        "before": {},
        "after": {}
    }

    meta = transaction.get("meta") or {}

    pre_balances = meta.get("preTokenBalances") or []
    post_balances = meta.get("postTokenBalances") or []

    for balance in pre_balances:

        if balance.get("mint") != token_address:
            continue

        owner = balance.get("owner")

        if not owner:
            continue

        amount = (
            balance
            .get("uiTokenAmount", {})
            .get("uiAmount")
            or 0
        )

        result["before"][owner] = float(amount)

    for balance in post_balances:

        if balance.get("mint") != token_address:
            continue

        owner = balance.get("owner")

        if not owner:
            continue

        amount = (
            balance
            .get("uiTokenAmount", {})
            .get("uiAmount")
            or 0
        )

        result["after"][owner] = float(amount)

    return result


# =========================================================
# MOVIMENTAÇÃO DO TOKEN
# =========================================================

def analyze_dev_token_movements(
    wallet_address,
    token_address,
    limit=30
):

    signatures = solana_rpc(
        "getSignaturesForAddress",
        [
            wallet_address,
            {
                "limit": limit
            }
        ]
    )

    if not signatures:
        return {
            "in": 0.0,
            "out": 0.0,
            "transactions": 0,
            "counterparties": {}
        }

    total_in = 0.0
    total_out = 0.0
    counterparties = {}

    analyzed = 0

    for signature_info in signatures:

        signature = signature_info.get("signature")

        if not signature:
            continue

        if signature_info.get("err") is not None:
            continue

        transaction = get_transaction(signature)

        if not transaction:
            continue

        analyzed += 1

        balances = get_token_balance_map(
            transaction,
            token_address
        )

        before = balances["before"]
        after = balances["after"]

        owners = set(before.keys()) | set(after.keys())

        wallet_before = before.get(wallet_address, 0.0)
        wallet_after = after.get(wallet_address, 0.0)

        delta = wallet_after - wallet_before

        if delta > 0:
            total_in += delta

        elif delta < 0:
            total_out += abs(delta)

        for owner in owners:

            if owner == wallet_address:
                continue

            owner_before = before.get(owner, 0.0)
            owner_after = after.get(owner, 0.0)

            owner_delta = owner_after - owner_before

            if owner_delta == 0 or delta == 0:
                continue

            if owner not in counterparties:
                counterparties[owner] = {
                    "in": 0.0,
                    "out": 0.0,
                    "transactions": 0
                }

            counterparties[owner]["transactions"] += 1

            if delta > 0 and owner_delta < 0:
                counterparties[owner]["in"] += abs(delta)

            elif delta < 0 and owner_delta > 0:
                counterparties[owner]["out"] += abs(delta)

    return {
        "in": total_in,
        "out": total_out,
        "transactions": analyzed,
        "counterparties": counterparties
    }


# =========================================================
# POSSÍVEIS FUNDERS
# =========================================================

def analyze_possible_funders(wallet_address, limit=30):

    signatures = solana_rpc(
        "getSignaturesForAddress",
        [
            wallet_address,
            {
                "limit": limit
            }
        ]
    )

    if not signatures:
        return {}

    funders = {}

    for signature_info in signatures:

        signature = signature_info.get("signature")

        if not signature:
            continue

        if signature_info.get("err") is not None:
            continue

        transaction = get_transaction(signature)

        if not transaction:
            continue

        meta = transaction.get("meta") or {}

        pre_balances = meta.get("preBalances") or []
        post_balances = meta.get("postBalances") or []

        keys = get_account_keys(transaction)

        if not pre_balances or not post_balances:
            continue

        for index, key in enumerate(keys):

            pubkey = key.get("pubkey")

            if not pubkey:
                continue

            if pubkey == wallet_address:
                continue

            if index >= len(pre_balances):
                continue

            if index >= len(post_balances):
                continue

            before = pre_balances[index]
            after = post_balances[index]

            delta = after - before

            # A wallet receiving SOL enquanto a wallet analisada
            # perde SOL pode ser uma possível relação.
            if delta < 0:

                wallet_index = None

                for i, own_key in enumerate(keys):
                    if own_key.get("pubkey") == wallet_address:
                        wallet_index = i
                        break

                if wallet_index is None:
                    continue

                if wallet_index >= len(pre_balances):
                    continue

                if wallet_index >= len(post_balances):
                    continue

                wallet_delta = (
                    post_balances[wallet_index]
                    - pre_balances[wallet_index]
                )

                if wallet_delta > 0:

                    amount_sol = wallet_delta / 1_000_000_000

                    if pubkey not in funders:
                        funders[pubkey] = 0.0

                    funders[pubkey] += amount_sol

    return funders


# =========================================================
# COMPORTAMENTO DO DEV
# =========================================================

def classify_dev_behavior(
    token_balance,
    token_movements,
    funders
):

    score = 0
    reasons = []

    balance = token_balance.get("balance", 0.0)

    token_in = token_movements.get("in", 0.0)
    token_out = token_movements.get("out", 0.0)

    if token_out > 0:
        score += 40
        reasons.append("Saídas de token observadas")

    if token_in > 0:
        score += 10
        reasons.append("Entradas de token observadas")

    if balance > 0:
        score += 10
        reasons.append("Wallet ainda possui tokens")

    if funders:
        score += 5
        reasons.append("Possível financiamento identificado")

    score = min(score, 100)

    if score >= 60:
        status = "🔴 COMPORTAMENTO DE ATENÇÃO"

    elif score >= 30:
        status = "🟡 SINAL MODERADO"

    else:
        status = "🟢 SEM SINAL FORTE"

    return {
        "score": score,
        "status": status,
        "reasons": reasons
    }


# =========================================================
# HOLDER INTELLIGENCE
# =========================================================

def get_holder_intelligence(token_address, pair_address):

    result = solana_rpc(
        "getTokenLargestAccounts",
        [
            token_address
        ]
    )

    if not result:
        return None

    value = result.get("value") or []

    if not value:
        return None

    supply_result = solana_rpc(
        "getTokenSupply",
        [
            token_address
        ]
    )

    if not supply_result:
        return None

    supply_info = supply_result.get("value") or {}

    supply_raw = float(
        supply_info.get("amount") or 0
    )

    if supply_raw <= 0:
        return None

    owner_balances = {}

    pool_percentage = 0.0

    raw_top_10 = 0.0

    token_accounts_analyzed = 0

    for item in value[:20]:

        address = item.get("address")

        amount_raw = float(
            item.get("amount") or 0
        )

        if not address:
            continue

        percentage = (
            amount_raw / supply_raw
        ) * 100

        if token_accounts_analyzed < 10:
            raw_top_10 += percentage

        owner = get_token_account_owner(address)

        if not owner:
            continue

        token_accounts_analyzed += 1

        if is_liquidity_pool_wallet(
            owner,
            pair_address
        ):
            pool_percentage += percentage
            continue

        owner_balances[owner] = (
            owner_balances.get(owner, 0.0)
            + percentage
        )

    sorted_owners = sorted(
        owner_balances.items(),
        key=lambda x: x[1],
        reverse=True
    )

    real_concentration = sum(
        percentage
        for _, percentage in sorted_owners[:10]
    )

    if real_concentration < 20:
        real_status = "🟢 BAIXA"

    elif real_concentration < 40:
        real_status = "🟡 MODERADA"

    else:
        real_status = "🔴 ALTA"

    if raw_top_10 < 30:
        raw_status = "🟢 BAIXA"

    elif raw_top_10 < 50:
        raw_status = "🟡 MODERADA"

    else:
        raw_status = "🔴 ALTA"

    return {
        "accounts_analyzed": token_accounts_analyzed,
        "raw_top_10": raw_top_10,
        "raw_status": raw_status,
        "real_owners": len(sorted_owners),
        "real_concentration": real_concentration,
        "real_status": real_status,
        "pool_percentage": pool_percentage,
        "top_holders": sorted_owners[:5]
    }


# =========================================================
# SECURITY
# =========================================================

async def security(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Use assim:\n/security TOKEN_ADDRESS"
        )
        return

    token_address = context.args[0].strip()

    # -----------------------------------------------------
    # TOKEN ACCOUNT INFO
    # -----------------------------------------------------

    account = solana_rpc(
        "getAccountInfo",
        [
            token_address,
            {
                "encoding": "jsonParsed"
            }
        ]
    )

    if not account or not account.get("value"):
        await update.message.reply_text(
            "❌ Não consegui encontrar esse token na Solana."
        )
        return

    value = account["value"]

    data = value.get("data") or {}

    parsed = data.get("parsed") or {}

    info = parsed.get("info") or {}

    mint_authority = info.get("mintAuthority")

    freeze_authority = info.get("freezeAuthority")

    supply = info.get("supply", "N/D")

    decimals = info.get("decimals", "N/D")

    token_program = value.get("owner", "N/D")

    # -----------------------------------------------------
    # LIQUIDEZ
    # -----------------------------------------------------

    liquidity_data = get_liquidity_data(
        token_address
    )

    if liquidity_data:

        liquidity = liquidity_data["liquidity"]
        market_cap = liquidity_data["market_cap"]
        volume_24h = liquidity_data["volume_24h"]
        price_change = liquidity_data["price_change_24h"]
        dex = liquidity_data["dex"]
        pair_address = liquidity_data["pair_address"]

        if liquidity < 10000:
            liquidity_status = "🔴 BAIXA"

        elif liquidity < 50000:
            liquidity_status = "🟡 MODERADA"

        else:
            liquidity_status = "🟢 BOA"

    else:

        liquidity = 0
        market_cap = 0
        volume_24h = 0
        price_change = 0
        dex = "N/D"
        pair_address = "N/D"
        liquidity_status = "⚪ N/D"

    # -----------------------------------------------------
    # HOLDERS
    # -----------------------------------------------------

    holder_data = get_holder_intelligence(
        token_address,
        pair_address
    )

    # -----------------------------------------------------
    # DEV WALLET 3.0
    # -----------------------------------------------------

    deployer_data = identify_deployer_candidates(
        token_address,
        max_signatures=100
    )

    candidates = deployer_data["candidates"]

    strong_candidates = [
        candidate
        for candidate in candidates
        if candidate["score"] >= 70
    ]

    medium_candidates = [
        candidate
        for candidate in candidates
        if 40 <= candidate["score"] < 70
    ]

    # -----------------------------------------------------
    # MONTA MENSAGEM
    # -----------------------------------------------------

    message = "🛡️ SECURITY ENGINE\n\n"

    message += "🪙 Token:\n"
    message += f"{token_address}\n\n"

    # -----------------------------------------------------
    # MINT
    # -----------------------------------------------------

    message += "🔐 MINT AUTHORITY\n"

    if mint_authority:
        message += f"⚠️ ATIVA\n{mint_authority}\n"
    else:
        message += "✅ REVOGADA\n"

    message += "\n"

    # -----------------------------------------------------

    message += "🧊 FREEZE AUTHORITY\n"

    if freeze_authority:
        message += f"⚠️ ATIVA\n{freeze_authority}\n"
    else:
        message += "✅ REVOGADA\n"

    message += "\n"

    # -----------------------------------------------------

    message += "🪙 SUPPLY\n"
    message += f"{supply}\n\n"

    message += "🔢 DECIMAIS\n"
    message += f"{decimals}\n\n"

    message += "⚙️ TOKEN PROGRAM\n"
    message += f"{token_program}\n\n"

    # =====================================================
    # HOLDERS
    # =====================================================

    message += "👥 HOLDER INTELLIGENCE\n\n"

    if holder_data:

        message += (
            f"Token accounts analisadas: "
            f"{holder_data['accounts_analyzed']}\n"
        )

        message += (
            f"Top 10 bruto: "
            f"{holder_data['raw_top_10']:.2f}%\n"
        )

        message += (
            f"Concentração bruta: "
            f"{holder_data['raw_status']}\n\n"
        )

        message += (
            f"Owners reais identificados: "
            f"{holder_data['real_owners']}\n"
        )

        message += (
            f"Concentração real: "
            f"{holder_data['real_concentration']:.2f}%\n"
        )

        message += (
            f"Status real: "
            f"{holder_data['real_status']}\n\n"
        )

        message += "💧 POOL IDENTIFICADA\n\n"

        message += (
            f"Pool: {pair_address}\n"
        )

        message += (
            f"Tokens na pool: "
            f"{holder_data['pool_percentage']:.2f}%\n\n"
        )

        message += "👛 PRINCIPAIS HOLDERS REAIS\n\n"

        for index, (wallet, percentage) in enumerate(
            holder_data["top_holders"],
            start=1
        ):

            message += (
                f"{index}. {wallet}\n"
                f"   {percentage:.2f}%\n"
            )

        message += "\n"

    else:

        message += (
            "⚪ Não foi possível analisar os holders.\n\n"
        )

    # =====================================================
    # LIQUIDEZ
    # =====================================================

    message += "💧 LIQUIDEZ\n"

    message += (
        f"Liquidez: ${liquidity:,.0f}\n"
    )

    message += (
        f"Market Cap: ${market_cap:,.0f}\n"
    )

    message += (
        f"Volume 24h: ${volume_24h:,.0f}\n"
    )

    message += (
        f"Variação 24h: {price_change:.2f}%\n\n"
    )

    message += (
        f"Liquidez: {liquidity_status}\n"
    )

    message += f"DEX: {dex}\n"
    message += f"Pool: {pair_address}\n\n"

    # =====================================================
    # DEV WALLET 3.0
    # =====================================================

    message += "🧠 DEV WALLET INTELLIGENCE 3.0\n\n"

    message += (
        f"🔎 Transações do mint analisadas: "
        f"{deployer_data['transactions_scanned']}\n"
    )

    if deployer_data["initialization_found"]:

        message += (
            "🟢 Inicialização do mint encontrada.\n\n"
        )

        if strong_candidates:

            message += "🟢 CANDIDATO(S) COM FORTE EVIDÊNCIA\n\n"

        elif medium_candidates:

            message += "🟡 CANDIDATO(S) POSSÍVEIS\n\n"

        else:

            message += (
                "⚪ Inicialização encontrada, "
                "mas sem candidato forte.\n\n"
            )

        for index, candidate in enumerate(
            candidates[:5],
            start=1
        ):

            message += (
                f"{index}️⃣ {candidate['wallet']}\n"
            )

            message += (
                f"Score: {candidate['score']}/100\n"
            )

            message += (
                f"{candidate['status']}\n"
            )

            if candidate["reasons"]:

                message += "Evidências:\n"

                for reason in candidate["reasons"]:

                    if reason == "Mint authority":
                        message += "✅ Mint authority\n"

                    elif reason == "Freeze authority":
                        message += "⚠️ Freeze authority\n"

                    elif reason == "Fee payer":
                        message += "✅ Fee payer\n"

                    elif reason == "Signer":
                        message += "✅ Signer\n"

                    elif reason == "Participou da inicialização":
                        message += (
                            "✅ Participou da inicialização\n"
                        )

            if candidate["initialize_mint_count"] > 0:

                message += (
                    f"initializeMint: "
                    f"{candidate['initialize_mint_count']}x\n"
                )

            if candidate["initialize_mint2_count"] > 0:

                message += (
                    f"initializeMint2: "
                    f"{candidate['initialize_mint2_count']}x\n"
                )

            if candidate["programs"]:

                message += (
                    "Programas: "
                    + ", ".join(candidate["programs"])
                    + "\n"
                )

            if candidate["first_initialization"]:

                message += (
                    "Primeira inicialização: "
                    + format_timestamp(
                        candidate["first_initialization"]
                    )
                    + "\n"
                )

            message += "\n"

    else:

        message += (
            "⚪ INITIALIZE MINT NÃO ENCONTRADO\n\n"
        )

        message += (
            "Nenhuma transação analisada apresentou "
            "evidência direta de initializeMint/"
            "initializeMint2.\n\n"
        )

        if candidates:

            message += (
                "⚠️ Algumas wallets apareceram "
                "nas transações do token, mas isso "
                "não é suficiente para chamá-las de deployer.\n\n"
            )

            for index, candidate in enumerate(
                candidates[:3],
                start=1
            ):

                message += (
                    f"{index}️⃣ {candidate['wallet']}\n"
                )

                message += (
                    f"Score: {candidate['score']}/100\n"
                )

                message += (
                    f"{candidate['status']}\n\n"
                )

        else:

            message += (
                "⚪ DEPLOYER NÃO IDENTIFICADO\n\n"
            )

    message += (
        "⚠️ IMPORTANTE\n"
        "A análise identifica candidatos com base "
        "em evidências on-chain. Isso não prova "
        "a identidade real do desenvolvedor.\n\n"
    )

    # =====================================================
    # ANÁLISE INDIVIDUAL DO MELHOR CANDIDATO
    # =====================================================

    if candidates:

        best = candidates[0]

        # Só fazemos análise comportamental se houver
        # alguma evidência mínima.
        if best["score"] >= 40:

            wallet = best["wallet"]

            wallet_balance = get_wallet_token_balance(
                wallet,
                token_address
            )

            token_movements = analyze_dev_token_movements(
                wallet,
                token_address,
                limit=30
            )

            funders = analyze_possible_funders(
                wallet,
                limit=30
            )

            behavior = classify_dev_behavior(
                wallet_balance,
                token_movements,
                funders
            )

            message += "👛 ANÁLISE COMPORTAMENTAL\n\n"

            message += (
                f"Wallet analisada:\n{wallet}\n\n"
            )

            message += (
                "💰 TOKEN ATUALMENTE NA WALLET\n"
            )

            message += (
                f"{wallet_balance['balance']:.6f}\n"
            )

            message += (
                f"Contas do token: "
                f"{wallet_balance['accounts']}\n\n"
            )

            message += "🔄 MOVIMENTAÇÃO DO TOKEN\n"

            message += (
                f"Entradas observadas: "
                f"{token_movements['in']:.6f}\n"
            )

            message += (
                f"Saídas observadas: "
                f"{token_movements['out']:.6f}\n\n"
            )

            message += "💸 POSSÍVEIS FONTES DE FINANCIAMENTO\n"

            if funders:

                sorted_funders = sorted(
                    funders.items(),
                    key=lambda x: x[1],
                    reverse=True
                )

                for funder, amount in sorted_funders[:5]:

                    message += (
                        f"• {funder}: "
                        f"{amount:.4f} SOL\n"
                    )

            else:

                message += (
                    "Nenhuma fonte de financiamento "
                    "clara identificada.\n"
                )

            message += "\n"

            message += "🧭 COMPORTAMENTO\n"

            message += (
                f"{behavior['status']}\n"
            )

            message += (
                f"Índice interno: "
                f"{behavior['score']}/100\n"
            )

            if behavior["reasons"]:

                message += "\n"

                for reason in behavior["reasons"]:

                    message += (
                        f"• {reason}\n"
                    )

            message += "\n"

    # =====================================================
    # PRÓXIMAS ETAPAS
    # =====================================================

    message += "📊 PRÓXIMAS ANÁLISES\n\n"

    message += "• Histórico on-chain completo\n"
    message += "• Relação entre wallets\n"
    message += "• Funding em cadeia\n"
    message += "• Comportamento da liquidez\n"
    message += "• Distribuição coordenada\n"
    message += "• Risco de rug pull\n\n"

    message += (
        "⚠️ Ainda não é um Security Score."
    )

    await update.message.reply_text(
        message
    )


# =========================================================
# TOP MARKET
# =========================================================

def calculate_market_score(pair):

    liquidity = float(
        (pair.get("liquidity") or {}).get("usd") or 0
    )

    volume = float(
        (pair.get("volume") or {}).get("h24") or 0
    )

    movement = float(
        (pair.get("priceChange") or {}).get("h24") or 0
    )

    # Liquidez
    liquidity_score = min(
        liquidity / 50000 * 30,
        30
    )

    # Volume
    volume_score = min(
        volume / 500000 * 30,
        30
    )

    # Movimento
    if movement >= 50:
        movement_score = 5

    else:
        movement_score = min(
            max(movement, 0) / 20 * 20,
            20
        )

    # Relação volume/liquidez
    if liquidity > 0:
        ratio = volume / liquidity

        ratio_score = min(
            ratio / 10 * 20,
            20
        )

    else:
        ratio_score = 0

    score = (
        liquidity_score
        + volume_score
        + movement_score
        + ratio_score
    )

    return round(score)


async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        profile_url = (
            "https://api.dexscreener.com/"
            "token-profiles/latest/v1"
        )

        response = requests.get(
            profile_url,
            timeout=20
        )

        response.raise_for_status()

        profiles = response.json()

        solana_tokens = []

        for profile in profiles:

            if profile.get("chainId") != "solana":
                continue

            address = profile.get("tokenAddress")

            if not address:
                continue

            solana_tokens.append(address)

        candidates = []

        for address in solana_tokens[:30]:

            try:

                url = (
                    "https://api.dexscreener.com/"
                    f"latest/dex/tokens/{address}"
                )

                response = requests.get(
                    url,
                    timeout=15
                )

                if response.status_code != 200:
                    continue

                data = response.json()

                pairs = data.get("pairs") or []

                solana_pairs = [
                    pair
                    for pair in pairs
                    if pair.get("chainId") == "solana"
                ]

                if not solana_pairs:
                    continue

                solana_pairs.sort(
                    key=lambda x: float(
                        (x.get("liquidity") or {}).get("usd") or 0
                    ),
                    reverse=True
                )

                pair = solana_pairs[0]

                base_token = pair.get("baseToken") or {}

                symbol = base_token.get("symbol") or "N/D"
                name = base_token.get("name") or "N/D"

                if symbol in ["SOL", "WSOL"]:
                    continue

                liquidity = float(
                    (pair.get("liquidity") or {}).get("usd") or 0
                )

                volume = float(
                    (pair.get("volume") or {}).get("h24") or 0
                )

                movement = float(
                    (pair.get("priceChange") or {}).get("h24") or 0
                )

                market_cap = float(
                    pair.get("marketCap")
                    or pair.get("fdv")
                    or 0
                )

                if liquidity < 15000:
                    continue

                if volume < 10000:
                    continue

                score = calculate_market_score(pair)

                candidates.append({
                    "name": name,
                    "symbol": symbol,
                    "address": address,
                    "liquidity": liquidity,
                    "volume": volume,
                    "movement": movement,
                    "market_cap": market_cap,
                    "score": score
                })

            except Exception:
                continue

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        candidates = candidates[:5]

        if not candidates:

            await update.message.reply_text(
                "⚪ Nenhum token encontrado no momento."
            )

            return

        message = "📊 MARKET ENGINE — TOP 5\n\n"

        for index, token in enumerate(
            candidates,
            start=1
        ):

            message += (
                f"{index}. {token['name']} "
                f"({token['symbol']})\n"
            )

            message += (
                f"Score: {token['score']}/100\n"
            )

            message += (
                f"Liquidez: "
                f"${token['liquidity']:,.0f}\n"
            )

            message += (
                f"Volume 24h: "
                f"${token['volume']:,.0f}\n"
            )

            message += (
                f"Movimento: "
                f"{token['movement']:.2f}%\n"
            )

            message += (
                f"Market Cap: "
                f"${token['market_cap']:,.0f}\n"
            )

            message += (
                f"Token:\n"
                f"{token['address']}\n\n"
            )

        message += (
            "⚠️ O Market Engine avalia apenas "
            "dados de mercado.\n"
            "Ainda não considera segurança, "
            "wallets, comunidade ou notícias."
        )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        print("TOP ERROR:", e)

        await update.message.reply_text(
            "❌ Erro ao consultar o Market Engine."
        )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = (
        "🤖 MEME RADAR AI\n\n"
        "Bot de análise de tokens Solana.\n\n"
        "Comandos disponíveis:\n\n"
        "/top\n"
        "→ Ranking de oportunidades de mercado\n\n"
        "/security TOKEN\n"
        "→ Análise de segurança e wallets\n\n"
        "/help\n"
        "→ Ajuda"
    )

    await update.message.reply_text(
        message
    )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "📚 MEME RADAR AI\n\n"
        "/top\n"
        "Mostra os tokens com maior atividade "
        "de mercado.\n\n"
        "/security TOKEN_ADDRESS\n"
        "Analisa:\n"
        "• Mint authority\n"
        "• Freeze authority\n"
        "• Holder concentration\n"
        "• Liquidez\n"
        "• Pool\n"
        "• Deployer candidates\n"
        "• Histórico da wallet\n"
        "• Movimentação do token\n"
        "• Possíveis funders\n\n"
        "⚠️ O bot não garante valorização."
    )

    await update.message.reply_text(
        message
    )


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        Application
        .builder()
        .token(TELEGRAM_TOKEN)
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

    print("🤖 Meme Radar AI iniciado.")

    application.run_polling()


if __name__ == "__main__":
    main()
