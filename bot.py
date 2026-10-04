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
# CONSTANTES SOLANA
# =========================================================

TOKEN_PROGRAM_ID = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)

TOKEN_2022_PROGRAM_ID = (
    "TokenzQdBNLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)

SYSTEM_PROGRAM_ID = (
    "11111111111111111111111111111111"
)


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

            print(
                "RPC ERROR:",
                data["error"]
            )

            return None

        return data.get("result")

    except Exception as e:

        print(
            "RPC EXCEPTION:",
            e
        )

        return None


# =========================================================
# DEXSCREENER
# =========================================================

def get_liquidity_data(token_address):

    try:

        url = (
            "https://api.dexscreener.com/"
            f"latest/dex/tokens/{token_address}"
        )

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

        return {
            "liquidity": float(
                (pair.get("liquidity") or {}).get("usd") or 0
            ),
            "market_cap": float(
                pair.get("marketCap")
                or pair.get("fdv")
                or 0
            ),
            "volume_24h": float(
                (pair.get("volume") or {}).get("h24") or 0
            ),
            "price_change_24h": float(
                (pair.get("priceChange") or {}).get("h24") or 0
            ),
            "dex": pair.get("dexId") or "N/D",
            "pair_address": pair.get("pairAddress") or "N/D",
            "symbol": (
                pair.get("baseToken") or {}
            ).get("symbol") or "N/D",
            "name": (
                pair.get("baseToken") or {}
            ).get("name") or "N/D"
        }

    except Exception as e:

        print(
            "DEXSCREENER ERROR:",
            e
        )

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
# POOL
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

        return dt.strftime(
            "%d/%m/%Y %H:%M UTC"
        )

    except Exception:

        return "N/D"


# =========================================================
# MINT SIGNATURES
# =========================================================

def get_mint_signatures(
    token_address,
    limit=100
):

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
# TRANSACTION
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

        account_keys = (
            message.get("accountKeys") or []
        )

        result = []

        for key in account_keys:

            if isinstance(key, dict):

                pubkey = key.get("pubkey")

                if pubkey:

                    result.append({
                        "pubkey": pubkey,
                        "signer": bool(
                            key.get("signer")
                        ),
                        "writable": bool(
                            key.get("writable")
                        )
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

    keys = get_account_keys(
        transaction
    )

    return [
        item["pubkey"]
        for item in keys
        if item.get("signer")
    ]


# =========================================================
# FEE PAYER
# =========================================================

def get_fee_payer(transaction):

    keys = get_account_keys(
        transaction
    )

    if not keys:
        return None

    return keys[0].get("pubkey")


# =========================================================
# INSTRUÇÕES
# =========================================================

def extract_instructions(transaction):

    instructions = []

    try:

        message = (
            transaction
            .get("transaction", {})
            .get("message", {})
        )

        top_level = (
            message.get("instructions") or []
        )

        for index, instruction in enumerate(
            top_level
        ):

            instructions.append({
                "instruction": instruction,
                "source": "top-level",
                "index": index
            })

        meta = transaction.get("meta") or {}

        inner_groups = (
            meta.get("innerInstructions") or []
        )

        for group in inner_groups:

            parent_index = group.get("index")

            for index, instruction in enumerate(
                group.get("instructions") or []
            ):

                instructions.append({
                    "instruction": instruction,
                    "source": "inner",
                    "index": index,
                    "parent_index": parent_index
                })

    except Exception as e:

        print(
            "INSTRUCTION ERROR:",
            e
        )

    return instructions


# =========================================================
# DETECTA PROGRAM ID
# =========================================================

def get_instruction_program_id(
    instruction
):

    if not isinstance(
        instruction,
        dict
    ):
        return None

    return (
        instruction.get("programId")
        or instruction.get("program")
    )


# =========================================================
# EXTRAI CONTAS DA INSTRUÇÃO
# =========================================================

def get_instruction_accounts(
    instruction
):

    if not isinstance(
        instruction,
        dict
    ):
        return []

    accounts = (
        instruction.get("accounts")
        or []
    )

    result = []

    for account in accounts:

        if isinstance(
            account,
            str
        ):

            result.append(account)

        elif isinstance(
            account,
            dict
        ):

            pubkey = account.get(
                "pubkey"
            )

            if pubkey:
                result.append(pubkey)

    return result


# =========================================================
# IDENTIFICA INITIALIZE MINT
# =========================================================

def inspect_mint_initialization(
    transaction,
    token_address
):

    findings = []

    instructions = extract_instructions(
        transaction
    )

    for item in instructions:

        instruction = item["instruction"]

        if not isinstance(
            instruction,
            dict
        ):
            continue

        parsed = instruction.get(
            "parsed"
        )

        if isinstance(
            parsed,
            dict
        ):

            instruction_type = (
                parsed.get("type")
            )

            if instruction_type in [
                "initializeMint",
                "initializeMint2"
            ]:

                info = (
                    parsed.get("info")
                    or {}
                )

                mint = info.get(
                    "mint"
                )

                if mint == token_address:

                    findings.append({
                        "type": instruction_type,
                        "source": item["source"],
                        "program": (
                            instruction.get(
                                "program"
                            )
                            or "N/D"
                        ),
                        "program_id": (
                            instruction.get(
                                "programId"
                            )
                            or "N/D"
                        ),
                        "info": info,
                        "raw_accounts": (
                            get_instruction_accounts(
                                instruction
                            )
                        ),
                        "parsed": True
                    )

                    continue

        # -------------------------------------------------
        # INSTRUÇÃO NÃO PARSEADA
        # -------------------------------------------------

        program_id = (
            instruction.get(
                "programId"
            )
        )

        accounts = (
            get_instruction_accounts(
                instruction
            )
        )

        data = instruction.get(
            "data"
        )

        if not data:
            data = ""

        if token_address not in accounts:
            continue

        if program_id not in [
            TOKEN_PROGRAM_ID,
            TOKEN_2022_PROGRAM_ID
        ]:
            continue

        findings.append({
            "type": "unknown_token_instruction",
            "source": item["source"],
            "program": (
                instruction.get(
                    "program"
                )
                or "unknown"
            ),
            "program_id": program_id,
            "info": {},
            "raw_accounts": accounts,
            "data": data,
            "parsed": False
        })

    return findings


# =========================================================
# DETECTA CREATE ACCOUNT
# =========================================================

def inspect_create_account(
    transaction,
    token_address
):

    findings = []

    instructions = extract_instructions(
        transaction
    )

    for item in instructions:

        instruction = item["instruction"]

        if not isinstance(
            instruction,
            dict
        ):
            continue

        parsed = instruction.get(
            "parsed"
        )

        if not isinstance(
            parsed,
            dict
        ):
            continue

        instruction_type = (
            parsed.get("type")
        )

        if instruction_type != "createAccount":
            continue

        info = (
            parsed.get("info")
            or {}
        )

        new_account = info.get(
            "newAccount"
        )

        owner = info.get(
            "owner"
        )

        if new_account != token_address:
            continue

        if owner not in [
            TOKEN_PROGRAM_ID,
            TOKEN_2022_PROGRAM_ID
        ]:

            continue

        findings.append({
            "source": item["source"],
            "program": (
                instruction.get(
                    "program"
                )
                or "system"
            ),
            "program_id": (
                instruction.get(
                    "programId"
                )
                or SYSTEM_PROGRAM_ID
            ),
            "owner": owner,
            "new_account": new_account,
            "info": info
        })

    return findings


# =========================================================
# LOGS
# =========================================================

def get_transaction_logs(
    transaction
):

    meta = transaction.get(
        "meta"
    ) or {}

    logs = (
        meta.get(
            "logMessages"
        )
        or []
    )

    return logs


# =========================================================
# INVESTIGA A TRANSAÇÃO DE CRIAÇÃO
# =========================================================

def analyze_creation_transaction(
    transaction,
    token_address,
    signature
):

    initialization = (
        inspect_mint_initialization(
            transaction,
            token_address
        )
    )

    create_accounts = (
        inspect_create_account(
            transaction,
            token_address
        )
    )

    fee_payer = get_fee_payer(
        transaction
    )

    signers = get_transaction_signers(
        transaction
    )

    logs = get_transaction_logs(
        transaction
    )

    evidence = []

    for finding in initialization:

        evidence.append({
            "type": "initialization",
            "signature": signature,
            "finding": finding,
            "fee_payer": fee_payer,
            "signers": signers,
            "logs": logs
        })

    for finding in create_accounts:

        evidence.append({
            "type": "create_account",
            "signature": signature,
            "finding": finding,
            "fee_payer": fee_payer,
            "signers": signers,
            "logs": logs
        })

    return {
        "initialization": initialization,
        "create_accounts": create_accounts,
        "fee_payer": fee_payer,
        "signers": signers,
        "logs": logs,
        "evidence": evidence
    }


# =========================================================
# DEV WALLET INTELLIGENCE 3.1
# =========================================================

def identify_deployer_candidates(
    token_address,
    max_signatures=100
):

    signatures = get_mint_signatures(
        token_address,
        limit=max_signatures
    )

    if not signatures:

        return {
            "candidates": [],
            "initialization_found": False,
            "create_account_found": False,
            "transactions_scanned": 0,
            "creation_transactions": []
        }

    # getSignaturesForAddress retorna
    # do mais novo para o mais antigo.
    ordered_signatures = list(
        reversed(signatures)
    )

    candidate_map = {}

    creation_transactions = []

    transactions_scanned = 0

    for signature_info in ordered_signatures:

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        if signature_info.get("err") is not None:
            continue

        transaction = get_transaction(
            signature
        )

        transactions_scanned += 1

        if not transaction:
            continue

        analysis = analyze_creation_transaction(
            transaction,
            token_address,
            signature
        )

        initialization = analysis[
            "initialization"
        ]

        create_accounts = analysis[
            "create_accounts"
        ]

        # -------------------------------------------------
        # Só guardamos transações que tenham
        # alguma evidência relevante.
        # -------------------------------------------------

        if not initialization and not create_accounts:
            continue

        creation_transactions.append({
            "signature": signature,
            "slot": transaction.get(
                "slot"
            ),
            "block_time": transaction.get(
                "blockTime"
            ),
            "fee_payer": analysis[
                "fee_payer"
            ],
            "signers": analysis[
                "signers"
            ],
            "initialization": initialization,
            "create_accounts": create_accounts
        })

        fee_payer = analysis[
            "fee_payer"
        ]

        signers = analysis[
            "signers"
        ]

        # -------------------------------------------------
        # INITIALIZE MINT
        # -------------------------------------------------

        for finding in initialization:

            info = (
                finding.get(
                    "info"
                )
                or {}
            )

            mint_authority = info.get(
                "mintAuthority"
            )

            freeze_authority = info.get(
                "freezeAuthority"
            )

            wallets = set()

            if fee_payer:
                wallets.add(
                    fee_payer
                )

            for signer in signers:
                wallets.add(
                    signer
                )

            if mint_authority:
                wallets.add(
                    mint_authority
                )

            if freeze_authority:
                wallets.add(
                    freeze_authority
                )

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
                        "create_account_count": 0,
                        "programs": set(),
                        "program_ids": set(),
                        "signatures": [],
                        "first_evidence": None
                    }

                candidate = candidate_map[
                    wallet
                ]

                if wallet == fee_payer:
                    candidate[
                        "fee_payer_count"
                    ] += 1

                if wallet in signers:
                    candidate[
                        "signer_count"
                    ] += 1

                if wallet == mint_authority:
                    candidate[
                        "mint_authority_count"
                    ] += 1

                if wallet == freeze_authority:
                    candidate[
                        "freeze_authority_count"
                    ] += 1

                candidate[
                    "initialize_count"
                ] += 1

                if finding.get(
                    "type"
                ) == "initializeMint":

                    candidate[
                        "initialize_mint_count"
                    ] += 1

                if finding.get(
                    "type"
                ) == "initializeMint2":

                    candidate[
                        "initialize_mint2_count"
                    ] += 1

                program = finding.get(
                    "program"
                )

                if program:
                    candidate[
                        "programs"
                    ].add(program)

                program_id = finding.get(
                    "program_id"
                )

                if program_id:
                    candidate[
                        "program_ids"
                    ].add(program_id)

                if signature not in candidate[
                    "signatures"
                ]:

                    candidate[
                        "signatures"
                    ].append(
                        signature
                    )

                block_time = transaction.get(
                    "blockTime"
                )

                if (
                    candidate[
                        "first_evidence"
                    ] is None
                    or (
                        block_time is not None
                        and block_time <
                        candidate[
                            "first_evidence"
                        ]
                    )
                ):

                    candidate[
                        "first_evidence"
                    ] = block_time

        # -------------------------------------------------
        # CREATE ACCOUNT
        # -------------------------------------------------

        for finding in create_accounts:

            if fee_payer:

                wallet = fee_payer

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
                        "create_account_count": 0,
                        "programs": set(),
                        "program_ids": set(),
                        "signatures": [],
                        "first_evidence": None
                    }

                candidate = candidate_map[
                    wallet
                ]

                candidate[
                    "create_account_count"
                ] += 1

                candidate[
                    "fee_payer_count"
                ] += 1

                for signer in signers:

                    if signer == wallet:
                        candidate[
                            "signer_count"
                        ] += 1

                if signature not in candidate[
                    "signatures"
                ]:

                    candidate[
                        "signatures"
                    ].append(
                        signature
                    )

                owner = finding.get(
                    "owner"
                )

                if owner:
                    candidate[
                        "program_ids"
                    ].add(owner)

    # =====================================================
    # CALCULA SCORE
    # =====================================================

    candidates = []

    for wallet, candidate in candidate_map.items():

        score = 0
        reasons = []

        # -------------------------------------------------
        # MAIS FORTE
        # -------------------------------------------------

        if candidate[
            "mint_authority_count"
        ] > 0:

            score += 35

            reasons.append(
                "Mint authority"
            )

        if candidate[
            "freeze_authority_count"
        ] > 0:

            score += 15

            reasons.append(
                "Freeze authority"
            )

        # -------------------------------------------------
        # FEE PAYER
        # -------------------------------------------------

        if candidate[
            "fee_payer_count"
        ] > 0:

            score += 20

            reasons.append(
                "Fee payer"
            )

        # -------------------------------------------------
        # SIGNER
        # -------------------------------------------------

        if candidate[
            "signer_count"
        ] > 0:

            score += 15

            reasons.append(
                "Signer"
            )

        # -------------------------------------------------
        # INITIALIZE
        # -------------------------------------------------

        if candidate[
            "initialize_count"
        ] > 0:

            score += 15

            reasons.append(
                "Participou da inicialização"
            )

        # -------------------------------------------------
        # CREATE ACCOUNT
        # -------------------------------------------------

        if candidate[
            "create_account_count"
        ] > 0:

            score += 10

            reasons.append(
                "Criou a conta do mint"
            )

        score = min(
            score,
            100
        )

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
            "fee_payer_count": candidate[
                "fee_payer_count"
            ],
            "signer_count": candidate[
                "signer_count"
            ],
            "mint_authority_count": candidate[
                "mint_authority_count"
            ],
            "freeze_authority_count": candidate[
                "freeze_authority_count"
            ],
            "initialize_count": candidate[
                "initialize_count"
            ],
            "initialize_mint_count": candidate[
                "initialize_mint_count"
            ],
            "initialize_mint2_count": candidate[
                "initialize_mint2_count"
            ],
            "create_account_count": candidate[
                "create_account_count"
            ],
            "programs": sorted(
                candidate[
                    "programs"
                ]
            ),
            "program_ids": sorted(
                candidate[
                    "program_ids"
                ]
            ),
            "signatures": candidate[
                "signatures"
            ],
            "first_evidence": candidate[
                "first_evidence"
            ]
        })

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return {
        "candidates": candidates,
        "initialization_found": any(
            len(
                tx["initialization"]
            ) > 0
            for tx in creation_transactions
        ),
        "create_account_found": any(
            len(
                tx["create_accounts"]
            ) > 0
            for tx in creation_transactions
        ),
        "transactions_scanned": transactions_scanned,
        "creation_transactions": creation_transactions
    }


# =========================================================
# HOLDER INTELLIGENCE
# =========================================================

def get_holder_intelligence(
    token_address,
    pair_address
):

    result = solana_rpc(
        "getTokenLargestAccounts",
        [
            token_address
        ]
    )

    if not result:
        return None

    value = result.get(
        "value"
    ) or []

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

    supply_info = (
        supply_result.get(
            "value"
        )
        or {}
    )

    supply_raw = float(
        supply_info.get(
            "amount"
        )
        or 0
    )

    if supply_raw <= 0:
        return None

    owner_balances = {}

    pool_percentage = 0.0

    raw_top_10 = 0.0

    token_accounts_analyzed = 0

    for index, item in enumerate(
        value[:20]
    ):

        address = item.get(
            "address"
        )

        amount_raw = float(
            item.get(
                "amount"
            )
            or 0
        )

        if not address:
            continue

        percentage = (
            amount_raw
            / supply_raw
        ) * 100

        if index < 10:

            raw_top_10 += percentage

        owner = get_token_account_owner(
            address
        )

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
            owner_balances.get(
                owner,
                0.0
            )
            + percentage
        )

    sorted_owners = sorted(
        owner_balances.items(),
        key=lambda x: x[1],
        reverse=True
    )

    real_concentration = sum(
        percentage
        for _, percentage
        in sorted_owners[:10]
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
        "accounts_analyzed":
            token_accounts_analyzed,
        "raw_top_10":
            raw_top_10,
        "raw_status":
            raw_status,
        "real_owners":
            len(sorted_owners),
        "real_concentration":
            real_concentration,
        "real_status":
            real_status,
        "pool_percentage":
            pool_percentage,
        "top_holders":
            sorted_owners[:5]
    }


# =========================================================
# WALLET TOKEN ACCOUNTS
# =========================================================

def get_wallet_token_accounts(
    wallet_address,
    token_address
):

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

    return result.get(
        "value"
    ) or []


# =========================================================
# SALDO TOKEN
# =========================================================

def get_wallet_token_balance(
    wallet_address,
    token_address
):

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

            token_amount = (
                info.get(
                    "tokenAmount"
                )
                or {}
            )

            amount = float(
                token_amount.get(
                    "uiAmount"
                )
                or 0
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

def get_token_balance_map(
    transaction,
    token_address
):

    result = {
        "before": {},
        "after": {}
    }

    meta = (
        transaction.get(
            "meta"
        )
        or {}
    )

    pre_balances = (
        meta.get(
            "preTokenBalances"
        )
        or []
    )

    post_balances = (
        meta.get(
            "postTokenBalances"
        )
        or []
    )

    for balance in pre_balances:

        if balance.get(
            "mint"
        ) != token_address:

            continue

        owner = balance.get(
            "owner"
        )

        if not owner:
            continue

        amount = (
            balance
            .get(
                "uiTokenAmount",
                {}
            )
            .get(
                "uiAmount"
            )
            or 0
        )

        result[
            "before"
        ][owner] = float(
            amount
        )

    for balance in post_balances:

        if balance.get(
            "mint"
        ) != token_address:

            continue

        owner = balance.get(
            "owner"
        )

        if not owner:
            continue

        amount = (
            balance
            .get(
                "uiTokenAmount",
                {}
            )
            .get(
                "uiAmount"
            )
            or 0
        )

        result[
            "after"
        ][owner] = float(
            amount
        )

    return result


# =========================================================
# DEV TOKEN MOVEMENTS
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

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        if signature_info.get(
            "err"
        ) is not None:

            continue

        transaction = get_transaction(
            signature
        )

        if not transaction:
            continue

        analyzed += 1

        balances = get_token_balance_map(
            transaction,
            token_address
        )

        before = balances[
            "before"
        ]

        after = balances[
            "after"
        ]

        wallet_before = before.get(
            wallet_address,
            0.0
        )

        wallet_after = after.get(
            wallet_address,
            0.0
        )

        delta = (
            wallet_after
            - wallet_before
        )

        if delta > 0:

            total_in += delta

        elif delta < 0:

            total_out += abs(
                delta
            )

        owners = (
            set(before.keys())
            | set(after.keys())
        )

        for owner in owners:

            if owner == wallet_address:
                continue

            owner_before = before.get(
                owner,
                0.0
            )

            owner_after = after.get(
                owner,
                0.0
            )

            owner_delta = (
                owner_after
                - owner_before
            )

            if (
                owner_delta == 0
                or delta == 0
            ):

                continue

            if owner not in counterparties:

                counterparties[owner] = {
                    "in": 0.0,
                    "out": 0.0,
                    "transactions": 0
                }

            counterparties[
                owner
            ]["transactions"] += 1

            if (
                delta > 0
                and owner_delta < 0
            ):

                counterparties[
                    owner
                ]["in"] += abs(
                    delta
                )

            elif (
                delta < 0
                and owner_delta > 0
            ):

                counterparties[
                    owner
                ]["out"] += abs(
                    delta
                )

    return {
        "in": total_in,
        "out": total_out,
        "transactions": analyzed,
        "counterparties": counterparties
    }


# =========================================================
# FUNDERS
# =========================================================

def analyze_possible_funders(
    wallet_address,
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
        return {}

    funders = {}

    for signature_info in signatures:

        signature = signature_info.get(
            "signature"
        )

        if not signature:
            continue

        if signature_info.get(
            "err"
        ) is not None:

            continue

        transaction = get_transaction(
            signature
        )

        if not transaction:
            continue

        meta = (
            transaction.get(
                "meta"
            )
            or {}
        )

        pre_balances = (
            meta.get(
                "preBalances"
            )
            or []
        )

        post_balances = (
            meta.get(
                "postBalances"
            )
            or []
        )

        keys = get_account_keys(
            transaction
        )

        if (
            not pre_balances
            or not post_balances
        ):

            continue

        wallet_index = None

        for i, key in enumerate(keys):

            if key.get(
                "pubkey"
            ) == wallet_address:

                wallet_index = i

                break

        if wallet_index is None:
            continue

        if wallet_index >= len(
            pre_balances
        ):
            continue

        if wallet_index >= len(
            post_balances
        ):
            continue

        wallet_delta = (
            post_balances[
                wallet_index
            ]
            - pre_balances[
                wallet_index
            ]
        )

        if wallet_delta <= 0:
            continue

        for index, key in enumerate(keys):

            pubkey = key.get(
                "pubkey"
            )

            if not pubkey:
                continue

            if pubkey == wallet_address:
                continue

            if index >= len(
                pre_balances
            ):
                continue

            if index >= len(
                post_balances
            ):
                continue

            delta = (
                post_balances[index]
                - pre_balances[index]
            )

            if delta >= 0:
                continue

            amount_sol = (
                wallet_delta
                / 1_000_000_000
            )

            if pubkey not in funders:
                funders[pubkey] = 0.0

            funders[pubkey] += amount_sol

    return funders


# =========================================================
# COMPORTAMENTO
# =========================================================

def classify_dev_behavior(
    token_balance,
    token_movements,
    funders
):

    score = 0

    reasons = []

    balance = token_balance.get(
        "balance",
        0.0
    )

    token_in = token_movements.get(
        "in",
        0.0
    )

    token_out = token_movements.get(
        "out",
        0.0
    )

    if token_out > 0:

        score += 40

        reasons.append(
            "Saídas de token observadas"
        )

    if token_in > 0:

        score += 10

        reasons.append(
            "Entradas de token observadas"
        )

    if balance > 0:

        score += 10

        reasons.append(
            "Wallet ainda possui tokens"
        )

    if funders:

        score += 5

        reasons.append(
            "Possível financiamento identificado"
        )

    score = min(
        score,
        100
    )

    if score >= 60:

        status = (
            "🔴 COMPORTAMENTO DE ATENÇÃO"
        )

    elif score >= 30:

        status = (
            "🟡 SINAL MODERADO"
        )

    else:

        status = (
            "🟢 SEM SINAL FORTE"
        )

    return {
        "score": score,
        "status": status,
        "reasons": reasons
    }


# =========================================================
# SECURITY
# =========================================================

async def security(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use assim:\n"
            "/security TOKEN_ADDRESS"
        )

        return

    token_address = (
        context.args[0].strip()
    )

    # -----------------------------------------------------
    # MINT ACCOUNT
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

    if (
        not account
        or not account.get("value")
    ):

        await update.message.reply_text(
            "❌ Não consegui encontrar "
            "esse token na Solana."
        )

        return

    value = account[
        "value"
    ]

    data = value.get(
        "data"
    ) or {}

    parsed = data.get(
        "parsed"
    ) or {}

    info = parsed.get(
        "info"
    ) or {}

    mint_authority = info.get(
        "mintAuthority"
    )

    freeze_authority = info.get(
        "freezeAuthority"
    )

    supply = info.get(
        "supply",
        "N/D"
    )

    decimals = info.get(
        "decimals",
        "N/D"
    )

    token_program = value.get(
        "owner",
        "N/D"
    )

    # -----------------------------------------------------
    # LIQUIDEZ
    # -----------------------------------------------------

    liquidity_data = get_liquidity_data(
        token_address
    )

    if liquidity_data:

        liquidity = (
            liquidity_data[
                "liquidity"
            ]
        )

        market_cap = (
            liquidity_data[
                "market_cap"
            ]
        )

        volume_24h = (
            liquidity_data[
                "volume_24h"
            ]
        )

        price_change = (
            liquidity_data[
                "price_change_24h"
            ]
        )

        dex = (
            liquidity_data[
                "dex"
            ]
        )

        pair_address = (
            liquidity_data[
                "pair_address"
            ]
        )

        if liquidity < 10000:

            liquidity_status = (
                "🔴 BAIXA"
            )

        elif liquidity < 50000:

            liquidity_status = (
                "🟡 MODERADA"
            )

        else:

            liquidity_status = (
                "🟢 BOA"
            )

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
    # DEV 3.1
    # -----------------------------------------------------

    deployer_data = identify_deployer_candidates(
        token_address,
        max_signatures=100
    )

    candidates = (
        deployer_data[
            "candidates"
        ]
    )

    # -----------------------------------------------------
    # MENSAGEM
    # -----------------------------------------------------

    message = (
        "🛡️ SECURITY ENGINE\n\n"
    )

    message += (
        "🪙 Token:\n"
        f"{token_address}\n\n"
    )

    message += (
        "🔐 MINT AUTHORITY\n"
    )

    if mint_authority:

        message += (
            "⚠️ ATIVA\n"
            f"{mint_authority}\n"
        )

    else:

        message += (
            "✅ REVOGADA\n"
        )

    message += "\n"

    message += (
        "🧊 FREEZE AUTHORITY\n"
    )

    if freeze_authority:

        message += (
            "⚠️ ATIVA\n"
            f"{freeze_authority}\n"
        )

    else:

        message += (
            "✅ REVOGADA\n"
        )

    message += "\n"

    message += (
        "🪙 SUPPLY\n"
        f"{supply}\n\n"
    )

    message += (
        "🔢 DECIMAIS\n"
        f"{decimals}\n\n"
    )

    message += (
        "⚙️ TOKEN PROGRAM\n"
        f"{token_program}\n\n"
    )

    # =====================================================
    # HOLDERS
    # =====================================================

    message += (
        "👥 HOLDER INTELLIGENCE\n\n"
    )

    if holder_data:

        message += (
            "Token accounts analisadas: "
            f"{holder_data['accounts_analyzed']}\n"
        )

        message += (
            "Top 10 bruto: "
            f"{holder_data['raw_top_10']:.2f}%\n"
        )

        message += (
            "Concentração bruta: "
            f"{holder_data['raw_status']}\n\n"
        )

        message += (
            "Owners reais identificados: "
            f"{holder_data['real_owners']}\n"
        )

        message += (
            "Concentração real: "
            f"{holder_data['real_concentration']:.2f}%\n"
        )

        message += (
            "Status real: "
            f"{holder_data['real_status']}\n\n"
        )

        message += (
            "💧 POOL IDENTIFICADA\n\n"
        )

        message += (
            f"Pool: {pair_address}\n"
        )

        message += (
            "Tokens na pool: "
            f"{holder_data['pool_percentage']:.2f}%\n\n"
        )

        message += (
            "👛 PRINCIPAIS HOLDERS REAIS\n\n"
        )

        for index, (
            wallet,
            percentage
        ) in enumerate(
            holder_data[
                "top_holders"
            ],
            start=1
        ):

            message += (
                f"{index}. {wallet}\n"
                f"   {percentage:.2f}%\n"
            )

        message += "\n"

    else:

        message += (
            "⚪ Não foi possível "
            "analisar os holders.\n\n"
        )

    # =====================================================
    # LIQUIDEZ
    # =====================================================

    message += (
        "💧 LIQUIDEZ\n"
    )

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
        f"Variação 24h: "
        f"{price_change:.2f}%\n\n"
    )

    message += (
        f"Liquidez: "
        f"{liquidity_status}\n"
    )

    message += (
        f"DEX: {dex}\n"
    )

    message += (
        f"Pool: {pair_address}\n\n"
    )

    # =====================================================
    # DEV 3.1
    # =====================================================

    message += (
        "🧠 DEV WALLET INTELLIGENCE 3.1\n\n"
    )

    message += (
        "🔎 Transações do mint analisadas: "
        f"{deployer_data['transactions_scanned']}\n"
    )

    if deployer_data[
        "initialization_found"
    ]:

        message += (
            "🟢 INITIALIZE MINT ENCONTRADO\n\n"
        )

    else:

        message += (
            "⚪ INITIALIZE MINT PARSED "
            "NÃO ENCONTRADO\n"
        )

    if deployer_data[
        "create_account_found"
    ]:

        message += (
            "🟢 CREATE ACCOUNT DO MINT "
            "ENCONTRADO\n\n"
        )

    else:

        message += (
            "⚪ CREATE ACCOUNT DO MINT "
            "NÃO ENCONTRADO\n\n"
        )

    # -----------------------------------------------------
    # CANDIDATOS
    # -----------------------------------------------------

    if candidates:

        message += (
            "🧠 DEPLOYER CANDIDATES\n\n"
        )

        for index, candidate in enumerate(
            candidates[:5],
            start=1
        ):

            message += (
                f"{index}️⃣ "
                f"{candidate['wallet']}\n"
            )

            message += (
                f"Score: "
                f"{candidate['score']}/100\n"
            )

            message += (
                f"{candidate['status']}\n"
            )

            if candidate[
                "reasons"
            ]:

                message += (
                    "Evidências:\n"
                )

                for reason in candidate[
                    "reasons"
                ]:

                    if reason == "Mint authority":

                        message += (
                            "✅ Mint authority\n"
                        )

                    elif reason == "Freeze authority":

                        message += (
                            "⚠️ Freeze authority\n"
                        )

                    elif reason == "Fee payer":

                        message += (
                            "✅ Fee payer\n"
                        )

                    elif reason == "Signer":

                        message += (
                            "✅ Signer\n"
                        )

                    elif reason == (
                        "Participou da inicialização"
                    ):

                        message += (
                            "✅ Participou da inicialização\n"
                        )

                    elif reason == (
                        "Criou a conta do mint"
                    ):

                        message += (
                            "✅ Criou a conta do mint\n"
                        )

            message += (
                "InitializeMint: "
                f"{candidate['initialize_mint_count']}x\n"
            )

            message += (
                "InitializeMint2: "
                f"{candidate['initialize_mint2_count']}x\n"
            )

            message += (
                "CreateAccount: "
                f"{candidate['create_account_count']}x\n"
            )

            if candidate[
                "programs"
            ]:

                message += (
                    "Programas: "
                    + ", ".join(
                        candidate[
                            "programs"
                        ]
                    )
                    + "\n"
                )

            if candidate[
                "program_ids"
            ]:

                message += (
                    "Program IDs:\n"
                    + "\n".join(
                        candidate[
                            "program_ids"
                        ][:3]
                    )
                    + "\n"
                )

            if candidate[
                "first_evidence"
            ]:

                message += (
                    "Primeira evidência: "
                    + format_timestamp(
                        candidate[
                            "first_evidence"
                        ]
                    )
                    + "\n"
                )

            message += "\n"

    else:

        message += (
            "⚪ DEPLOYER NÃO IDENTIFICADO\n\n"
        )

        message += (
            "Nenhuma wallet apresentou "
            "evidência suficiente para "
            "ser classificada como deployer.\n\n"
        )

    # =====================================================
    # INVESTIGAÇÃO DE CRIAÇÃO
    # =====================================================

    if deployer_data[
        "creation_transactions"
    ]:

        message += (
            "🔬 EVIDÊNCIAS DE CRIAÇÃO\n\n"
        )

        for tx in deployer_data[
            "creation_transactions"
        ][:3]:

            message += (
                "🧾 Transação:\n"
                f"{tx['signature']}\n"
            )

            message += (
                "⏱️ "
                + format_timestamp(
                    tx["block_time"]
                )
                + "\n"
            )

            if tx[
                "fee_payer"
            ]:

                message += (
                    "💳 Fee payer:\n"
                    f"{tx['fee_payer']}\n"
                )

            if tx[
                "initialization"
            ]:

                for finding in tx[
                    "initialization"
                ]:

                    message += (
                        "🪙 Inicialização: "
                        f"{finding['type']}\n"
                    )

                    message += (
                        "Programa: "
                        f"{finding['program']}\n"
                    )

                    message += (
                        "Program ID: "
                        f"{finding['program_id']}\n"
                    )

                    info = (
                        finding.get(
                            "info"
                        )
                        or {}
                    )

                    if info.get(
                        "mintAuthority"
                    ):

                        message += (
                            "Mint authority:\n"
                            f"{info['mintAuthority']}\n"
                        )

                    if (
                        "freezeAuthority"
                        in info
                    ):

                        message += (
                            "Freeze authority:\n"
                            f"{info.get('freezeAuthority')}\n"
                        )

            if tx[
                "create_accounts"
            ]:

                for finding in tx[
                    "create_accounts"
                ]:

                    message += (
                        "🏗️ CreateAccount "
                        "do mint encontrada\n"
                    )

                    message += (
                        "Owner: "
                        f"{finding['owner']}\n"
                    )

            message += "\n"

    # =====================================================
    # ANÁLISE COMPORTAMENTAL
    # =====================================================

    if candidates:

        best = candidates[0]

        if best[
            "score"
        ] >= 40:

            wallet = best[
                "wallet"
            ]

            wallet_balance = (
                get_wallet_token_balance(
                    wallet,
                    token_address
                )
            )

            token_movements = (
                analyze_dev_token_movements(
                    wallet,
                    token_address,
                    limit=30
                )
            )

            funders = (
                analyze_possible_funders(
                    wallet,
                    limit=30
                )
            )

            behavior = classify_dev_behavior(
                wallet_balance,
                token_movements,
                funders
            )

            message += (
                "👛 ANÁLISE COMPORTAMENTAL\n\n"
            )

            message += (
                "Wallet analisada:\n"
                f"{wallet}\n\n"
            )

            message += (
                "💰 TOKEN ATUALMENTE "
                "NA WALLET\n"
            )

            message += (
                f"{wallet_balance['balance']:.6f}\n"
            )

            message += (
                "Contas do token: "
                f"{wallet_balance['accounts']}\n\n"
            )

            message += (
                "🔄 MOVIMENTAÇÃO DO TOKEN\n"
            )

            message += (
                "Entradas observadas: "
                f"{token_movements['in']:.6f}\n"
            )

            message += (
                "Saídas observadas: "
                f"{token_movements['out']:.6f}\n\n"
            )

            message += (
                "💸 POSSÍVEIS FONTES "
                "DE FINANCIAMENTO\n"
            )

            if funders:

                sorted_funders = sorted(
                    funders.items(),
                    key=lambda x: x[1],
                    reverse=True
                )

                for funder, amount in (
                    sorted_funders[:5]
                ):

                    message += (
                        f"• {funder}: "
                        f"{amount:.4f} SOL\n"
                    )

            else:

                message += (
                    "Nenhuma fonte clara "
                    "identificada.\n"
                )

            message += "\n"

            message += (
                "🧭 COMPORTAMENTO\n"
                f"{behavior['status']}\n"
                f"Índice interno: "
                f"{behavior['score']}/100\n"
            )

            if behavior[
                "reasons"
            ]:

                message += "\n"

                for reason in behavior[
                    "reasons"
                ]:

                    message += (
                        f"• {reason}\n"
                    )

            message += "\n"

    # =====================================================
    # PRÓXIMAS ETAPAS
    # =====================================================

    message += (
        "📊 PRÓXIMAS ANÁLISES\n\n"
        "• Histórico on-chain completo\n"
        "• Relação entre wallets\n"
        "• Funding em cadeia\n"
        "• Comportamento da liquidez\n"
        "• Distribuição coordenada\n"
        "• Risco de rug pull\n\n"
        "⚠️ Ainda não é um Security Score."
    )

    await update.message.reply_text(
        message
    )


# =========================================================
# MARKET SCORE
# =========================================================

def calculate_market_score(pair):

    liquidity = float(
        (pair.get("liquidity") or {})
        .get("usd")
        or 0
    )

    volume = float(
        (pair.get("volume") or {})
        .get("h24")
        or 0
    )

    movement = float(
        (pair.get("priceChange") or {})
        .get("h24")
        or 0
    )

    liquidity_score = min(
        liquidity / 50000 * 30,
        30
    )

    volume_score = min(
        volume / 500000 * 30,
        30
    )

    if movement >= 50:

        movement_score = 5

    else:

        movement_score = min(
            max(movement, 0)
            / 20
            * 20,
            20
        )

    if liquidity > 0:

        ratio = (
            volume
            / liquidity
        )

        ratio_score = min(
            ratio / 10 * 20,
            20
        )

    else:

        ratio_score = 0

    return round(
        liquidity_score
        + volume_score
        + movement_score
        + ratio_score
    )


# =========================================================
# TOP
# =========================================================

async def top(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

            if profile.get(
                "chainId"
            ) != "solana":

                continue

            address = profile.get(
                "tokenAddress"
            )

            if address:

                solana_tokens.append(
                    address
                )

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

                pairs = (
                    data.get(
                        "pairs"
                    )
                    or []
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

                solana_pairs.sort(
                    key=lambda x: float(
                        (x.get("liquidity") or {})
                        .get("usd")
                        or 0
                    ),
                    reverse=True
                )

                pair = solana_pairs[0]

                base_token = (
                    pair.get(
                        "baseToken"
                    )
                    or {}
                )

                symbol = (
                    base_token.get(
                        "symbol"
                    )
                    or "N/D"
                )

                name = (
                    base_token.get(
                        "name"
                    )
                    or "N/D"
                )

                if symbol in [
                    "SOL",
                    "WSOL"
                ]:

                    continue

                liquidity = float(
                    (pair.get("liquidity") or {})
                    .get("usd")
                    or 0
                )

                volume = float(
                    (pair.get("volume") or {})
                    .get("h24")
                    or 0
                )

                movement = float(
                    (pair.get("priceChange") or {})
                    .get("h24")
                    or 0
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

                score = calculate_market_score(
                    pair
                )

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
                "⚪ Nenhum token encontrado "
                "no momento."
            )

            return

        message = (
            "📊 MARKET ENGINE — TOP 5\n\n"
        )

        for index, token in enumerate(
            candidates,
            start=1
        ):

            message += (
                f"{index}. "
                f"{token['name']} "
                f"({token['symbol']})\n"
            )

            message += (
                f"Score: "
                f"{token['score']}/100\n"
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
                "Token:\n"
                f"{token['address']}\n\n"
            )

        message += (
            "⚠️ O Market Engine avalia "
            "apenas dados de mercado.\n"
            "Ainda não considera segurança, "
            "wallets, comunidade ou notícias."
        )

        await update.message.reply_text(
            message
        )

    except Exception as e:

        print(
            "TOP ERROR:",
            e
        )

        await update.message.reply_text(
            "❌ Erro ao consultar "
            "o Market Engine."
        )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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
        "• CreateAccount\n"
        "• InitializeMint\n"
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
        .token(
            TELEGRAM_TOKEN
        )
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
