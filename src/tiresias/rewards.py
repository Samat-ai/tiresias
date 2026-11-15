from __future__ import annotations

import hashlib

from tiresias.contracts import PayoutReceipt, PayoutState


class RpcTimeout(Exception):
    pass


class UnknownSend(Exception):
    pass


class DevnetRewardService:
    def __init__(self, signer, rpc, *, lamports: int, recipient: str) -> None:
        self.signer = signer
        self.rpc = rpc
        self.lamports = lamports
        self.recipient = recipient
        self.network = "devnet"

    def prepare_payout(self, conn, payout_id: str) -> PayoutReceipt:
        row = conn.execute("SELECT * FROM payouts WHERE id = %s FOR UPDATE", (payout_id,)).fetchone()
        if row is None:
            raise KeyError(payout_id)
        if row["recipient"] != self.recipient or row["lamports"] != self.lamports or row["network"] != "devnet":
            raise PermissionError("client cannot choose the recipient, amount, or network")
        if row["signed_transaction"]:
            return _receipt(row)
        if row["state"] == PayoutState.UNKNOWN.value:
            return _receipt(row)
        signed = self.signer.sign(payout_id, row["recipient"], row["lamports"])
        conn.execute(
            """
            UPDATE payouts
            SET state = 'PREPARED', signed_transaction = %s, signature = %s,
                last_valid_block_height = %s, updated_at = now()
            WHERE id = %s AND signed_transaction IS NULL
            """,
            (signed["bytes"], signed["signature"], signed["last_valid_block_height"], payout_id),
        )
        fresh = conn.execute("SELECT * FROM payouts WHERE id = %s", (payout_id,)).fetchone()
        return _receipt(fresh)

    def reconcile_payout(self, conn, payout_id: str) -> PayoutReceipt:
        row = conn.execute("SELECT * FROM payouts WHERE id = %s FOR UPDATE", (payout_id,)).fetchone()
        if row["state"] == PayoutState.UNKNOWN.value:
            found = self.rpc.status(row["signature"]) if row["signature"] else None
            if found == "confirmed":
                conn.execute("UPDATE payouts SET state = 'CONFIRMED', updated_at = now() WHERE id = %s", (payout_id,))
            updated = conn.execute("SELECT * FROM payouts WHERE id = %s", (payout_id,)).fetchone()
            return _receipt(updated)
        if not row["signed_transaction"]:
            self.prepare_payout(conn, payout_id)
            row = conn.execute("SELECT * FROM payouts WHERE id = %s FOR UPDATE", (payout_id,)).fetchone()
        try:
            self.rpc.send(bytes(row["signed_transaction"]))
        except RpcTimeout:
            conn.execute("UPDATE payouts SET state = 'SUBMITTED', updated_at = now() WHERE id = %s", (payout_id,))
            updated = conn.execute("SELECT * FROM payouts WHERE id = %s", (payout_id,)).fetchone()
            return _receipt(updated)
        except UnknownSend:
            conn.execute("UPDATE payouts SET state = 'UNKNOWN', updated_at = now() WHERE id = %s", (payout_id,))
            updated = conn.execute("SELECT * FROM payouts WHERE id = %s", (payout_id,)).fetchone()
            return _receipt(updated)
        status = self.rpc.status(row["signature"])
        state = "CONFIRMED" if status == "confirmed" else "SUBMITTED"
        conn.execute("UPDATE payouts SET state = %s, updated_at = now() WHERE id = %s", (state, payout_id))
        updated = conn.execute("SELECT * FROM payouts WHERE id = %s", (payout_id,)).fetchone()
        return _receipt(updated)


def _receipt(row: dict) -> PayoutReceipt:
    return PayoutReceipt(
        payout_id=str(row["id"]),
        review_id=str(row["review_id"]),
        network=row["network"],
        lamports=row["lamports"],
        recipient=row["recipient"],
        signature=row["signature"],
        state=PayoutState(row["state"]),
        last_valid_block_height=row["last_valid_block_height"],
    )


class DeterministicSigner:
    def __init__(self) -> None:
        self.calls = 0

    def sign(self, payout_id: str, recipient: str, lamports: int) -> dict:
        self.calls += 1
        raw = f"{payout_id}:{recipient}:{lamports}".encode()
        return {
            "bytes": hashlib.sha256(raw).digest(),
            "signature": hashlib.sha256(raw).hexdigest(),
            "last_valid_block_height": 100,
        }
