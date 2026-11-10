"""Mais ações do Google além das básicas (agente/google.py): Gmail (etiquetas, anexos, responder), agendas, Drive,
Planilhas, Documentos e Tarefas.

Regra de ouro: o que sai para outras pessoas (compartilhar arquivo, convidar alguém, responder e-mail) ou não tem volta
(apagar e-mail de vez, mandar arquivo para a lixeira) **nunca roda direto**: vira uma AÇÃO guardada (`_stage`) e só
executa depois que o usuário respondeu sim, em uma mensagem posterior (`confirm_action`). O resto roda direto.
Toda chamada de escrita ainda passa pela lista fixa `WRITE_ALLOWED` de google.py.
"""

import base64
import re
import secrets
import time
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from . import google as g

ID_RE = re.compile(r"[A-Za-z0-9_@.\-]{3,200}")
LABEL_SYSTEM = {"INBOX", "UNREAD", "STARRED", "IMPORTANT", "TRASH", "SPAM", "SENT", "DRAFT"}
MAX_ORGANIZE = 100


def _id(value: str, what: str) -> str:
    if not ID_RE.fullmatch(value or ""):
        raise g.GoogleError(f"{what} inválido")
    return value


class GoogleExtra:
    """Misturado em GoogleClient: usa _get, _write, _account, turn e _staged do cliente."""

    # --- ações que esperam o sim do usuário -------------------------------------------------------------

    def _stage(self, label: str, email: str, call: Callable[[], Awaitable[Any]]) -> str:
        now = time.time()
        self._staged = {k: v for k, v in self._staged.items() if now - v[3] < g.TRASH_TTL_S}
        if len(self._staged) >= 20:
            raise g.GoogleError("há ações demais esperando o sim: confirme ou espere alguns minutos")
        action = secrets.token_hex(4)
        self._staged[action] = (label, call, self.turn, now)
        return (f"AÇÃO {action} (nada foi feito ainda): {label}\nMostre isto ao usuário e pergunte se pode fazer. Só depois do sim "
                f"dele, em uma mensagem nova, use confirmar_acao_google com a ação {action}.")

    async def confirm_action(self, action: str) -> str:
        item = self._staged.get(action or "")
        if item is None or time.time() - item[3] >= g.TRASH_TTL_S:
            self._staged.pop(action or "", None)
            raise g.GoogleError("essa ação não existe ou venceu: peça de novo")
        label, call, turn, _ = item
        if self.turn <= turn:
            raise g.GoogleError("o usuário ainda não respondeu: mostre a ação a ele e espere o sim")
        del self._staged[action]
        return await call()

    # --- Gmail: etiquetas, organizar, anexos, responder -------------------------------------------------

    async def list_labels(self, account: str = "") -> str:
        data = await self._get(account, "gmail", f"{g.GMAIL_API}/labels")
        return "\n".join(f"{x['name']}" for x in sorted(data.get("labels", []), key=lambda x: x["name"]))

    async def _label_id(self, email: str, name: str, create: bool) -> str:
        wanted = (name or "").strip()
        if not wanted:
            raise g.GoogleError("diga o nome da etiqueta")
        if wanted.upper() in LABEL_SYSTEM:
            return wanted.upper()
        for lab in (await self._get(email, "gmail", f"{g.GMAIL_API}/labels")).get("labels", []):
            if lab["name"].lower() == wanted.lower():
                return lab["id"]
        if not create:
            raise g.GoogleError(f"não existe a etiqueta '{wanted}' (veja listar_etiquetas_email)")
        made = await self._write(email, "gmail_organizar", "POST", f"{g.GMAIL_API}/labels", {
            "name": wanted[:100], "labelListVisibility": "labelShow", "messageListVisibility": "show"})
        return made["id"]

    async def organize_mail(self, query: str, action: str, label: str = "", limit: int = MAX_ORGANIZE, account: str = "") -> str:
        """Marca como lido/não lido, estrela, arquiva ou etiqueta e-mails (nada é apagado). Devolve a contagem exata."""
        email = self._account(account, "gmail_organizar")
        add: list[str] = []
        remove: list[str] = []
        if action == "lido":
            remove = ["UNREAD"]
        elif action == "nao_lido":
            add = ["UNREAD"]
        elif action == "estrela":
            add = ["STARRED"]
        elif action == "sem_estrela":
            remove = ["STARRED"]
        elif action == "arquivar":
            remove = ["INBOX"]
        elif action == "etiquetar":
            add = [await self._label_id(email, label, create=True)]
        elif action == "remover_etiqueta":
            remove = [await self._label_id(email, label, create=False)]
        else:
            raise g.GoogleError("ação inválida: use lido, nao_lido, estrela, sem_estrela, arquivar, etiquetar ou remover_etiqueta")
        limit = max(1, min(int(limit or MAX_ORGANIZE), MAX_ORGANIZE))
        data = await self._get(email, "gmail", f"{g.GMAIL_API}/messages", {"q": query or "in:inbox", "maxResults": limit})
        ids = [m["id"] for m in data.get("messages", [])]
        if not ids:
            return "nenhum e-mail encontrado com essa busca; nada mudou"
        await self._write(email, "gmail_organizar", "POST", f"{g.GMAIL_API}/messages/batchModify",
                          {"ids": ids, "addLabelIds": add, "removeLabelIds": remove})
        return f"{len(ids)} e-mail(s): ação '{action}'" + (f" ({label})" if label else "") + " aplicada"

    @staticmethod
    def _attachments(payload: dict) -> list[dict]:
        found: list[dict] = []

        def walk(part: dict) -> None:
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                found.append({"name": part["filename"], "mime": part.get("mimeType", ""), "id": part["body"]["attachmentId"],
                              "size": part["body"].get("size", 0)})
            for sub in part.get("parts", []) or []:
                walk(sub)

        walk(payload)
        return found

    async def list_attachments(self, message_id: str, account: str = "") -> str:
        m = await self._get(account, "gmail", f"{g.GMAIL_API}/messages/{_id(message_id, 'id de e-mail')}", {"format": "full"})
        rows = [f"{a['name']} · {a['mime']} · {a['size']} bytes · id {a['id']}" for a in self._attachments(m.get("payload", {}))]
        return g.UNTRUSTED + "\n" + g.clean("\n".join(rows)) if rows else "esse e-mail não tem anexos"

    async def read_attachment(self, message_id: str, attachment_id: str, account: str = "") -> str:
        """Lê anexo de texto (txt, csv, json, html...). PDF e imagem não são lidos aqui: abra pelo Gmail."""
        mid = _id(message_id, "id de e-mail")
        m = await self._get(account, "gmail", f"{g.GMAIL_API}/messages/{mid}", {"format": "full"})
        found = [a for a in self._attachments(m.get("payload", {})) if a["id"] == attachment_id]
        if not found:
            raise g.GoogleError("anexo não encontrado: use um id de ver_anexos_email")
        att = found[0]
        if not (att["mime"].startswith("text/") or att["mime"] in ("application/json", "application/xml", "text/csv")):
            raise g.GoogleError(f"não leio anexo desse tipo ({att['mime']}); só texto, CSV e JSON. Abra pelo Gmail")
        data = await self._get(account, "gmail", f"{g.GMAIL_API}/messages/{mid}/attachments/{quote(attachment_id, safe='')}")
        text = base64.urlsafe_b64decode(str(data.get("data", "")) + "==").decode("utf-8", "replace")
        return f"{g.UNTRUSTED}\n{g.clip(g.clean(text), g.MAX_MAIL)}"

    async def prepare_reply(self, message_id: str, body: str, account: str = "") -> str:
        """Passo 1 de responder um e-mail dentro da conversa. Nada é enviado antes do sim."""
        email = self._account(account, "gmail_enviar")
        m = await self._get(email, "gmail", f"{g.GMAIL_API}/messages/{_id(message_id, 'id de e-mail')}", {
            "format": "metadata", "metadataHeaders": ["From", "Reply-To", "Subject", "Message-ID", "References"]})
        h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
        match = re.search(r"[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+", h.get("reply-to") or h.get("from") or "")
        if not match:
            raise g.GoogleError("não achei para quem responder")
        subject = h.get("subject", "").strip().replace("\r", " ").replace("\n", " ")
        subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        headers = {}
        if h.get("message-id"):
            headers["In-Reply-To"] = h["message-id"].strip()
            headers["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
        return self._stage_send(email, [match.group(0)], subject, body, headers, m.get("threadId", ""))

    # --- agendas ----------------------------------------------------------------------------------------

    async def list_calendars(self, account: str = "") -> str:
        data = await self._get(account, "calendar", f"{g.CALENDAR_API}/users/me/calendarList")
        return "\n".join(f"{c.get('summaryOverride') or c.get('summary', '?')} · id {c['id']} · {c.get('accessRole', '')}"
                         for c in data.get("items", []))

    # --- Drive ------------------------------------------------------------------------------------------

    async def create_folder(self, name: str, parent: str = "", account: str = "") -> str:
        if not (name or "").strip():
            raise g.GoogleError("diga o nome da pasta")
        body: dict = {"name": name.strip()[:200], "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            body["parents"] = [g.file_id(parent)]
        email = self._account(account, "drive_escrever")
        done = await self._write(email, "drive_escrever", "POST", f"{g.DRIVE_API}/files", body)
        return f"pasta criada: {body['name']} (https://drive.google.com/drive/folders/{done.get('id', '')})"

    async def move_file(self, file: str, folder: str, account: str = "") -> str:
        fid, to = g.file_id(file), g.file_id(folder)
        email = self._account(account, "drive_escrever")
        meta = await self._get(email, "drive_escrever", f"{g.DRIVE_API}/files/{fid}", {"fields": "parents,name"})
        await self._write(email, "drive_escrever", "PATCH", f"{g.DRIVE_API}/files/{fid}", {},
                          {"addParents": to, "removeParents": ",".join(meta.get("parents", []))})
        return f"'{meta.get('name', fid)}' movido para a pasta"

    async def rename_file(self, file: str, name: str, account: str = "") -> str:
        if not (name or "").strip():
            raise g.GoogleError("diga o novo nome")
        email = self._account(account, "drive_escrever")
        await self._write(email, "drive_escrever", "PATCH", f"{g.DRIVE_API}/files/{g.file_id(file)}", {"name": name.strip()[:200]})
        return "arquivo renomeado"

    async def copy_file(self, file: str, name: str = "", account: str = "") -> str:
        email = self._account(account, "drive_escrever")
        done = await self._write(email, "drive_escrever", "POST", f"{g.DRIVE_API}/files/{g.file_id(file)}/copy",
                                 {"name": name.strip()[:200]} if name.strip() else {})
        return f"cópia criada (id {done.get('id', '')})"

    async def share_file(self, file: str, to: str, role: str = "reader", account: str = "") -> str:
        """Passo 1: compartilhar sai para outra pessoa, então só executa depois do sim."""
        fid = g.file_id(file)
        if not g.EMAIL_RE.fullmatch(to or ""):
            raise g.GoogleError("diga o e-mail de quem vai receber")
        if role not in ("reader", "commenter", "writer"):
            raise g.GoogleError("permissão inválida: reader (ver), commenter (comentar) ou writer (editar)")
        email = self._account(account, "drive_escrever")

        async def run() -> str:
            await self._write(email, "drive_escrever", "POST", f"{g.DRIVE_API}/files/{fid}/permissions",
                              {"type": "user", "role": role, "emailAddress": to}, {"sendNotificationEmail": "true"})
            return f"arquivo compartilhado com {to} ({role})"

        return self._stage(f"compartilhar o arquivo {fid} com {to} como '{role}' (a pessoa recebe um e-mail)", email, run)

    async def trash_file(self, file: str, account: str = "") -> str:
        fid = g.file_id(file)
        email = self._account(account, "drive_escrever")

        async def run() -> str:
            await self._write(email, "drive_escrever", "PATCH", f"{g.DRIVE_API}/files/{fid}", {"trashed": True})
            return "arquivo na lixeira do Drive (dá para restaurar em 30 dias)"

        return self._stage(f"mandar o arquivo {fid} para a lixeira do Drive", email, run)

    # --- Planilhas e Documentos -------------------------------------------------------------------------

    async def create_spreadsheet(self, title: str, tabs: str = "", account: str = "") -> str:
        if not (title or "").strip():
            raise g.GoogleError("diga o título da planilha")
        sheets = [{"properties": {"title": t.strip()[:100]}} for t in tabs.split(",") if t.strip()][:20]
        email = self._account(account, "sheets_escrever")
        done = await self._write(email, "sheets_escrever", "POST", g.SHEETS_API,
                                 {"properties": {"title": title.strip()[:200]}, **({"sheets": sheets} if sheets else {})})
        return f"planilha criada: {title.strip()} ({done.get('spreadsheetUrl', '')})"

    async def _sheet_ids(self, email: str, sid: str) -> dict[str, int]:
        meta = await self._get(email, "sheets_escrever", f"{g.SHEETS_API}/{sid}", {"fields": "sheets.properties(sheetId,title)"})
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    async def add_tab(self, ref: str, name: str, account: str = "") -> str:
        sid = g.sheet_id(ref)
        email = self._account(account, "sheets_escrever")
        await self._write(email, "sheets_escrever", "POST", f"{g.SHEETS_API}/{sid}:batchUpdate",
                          {"requests": [{"addSheet": {"properties": {"title": (name or "Nova aba").strip()[:100]}}}]})
        return "aba criada"

    async def clear_range(self, ref: str, cells: str, tab: str = "", account: str = "") -> str:
        sid = g.sheet_id(ref)
        if not re.fullmatch(r"[A-Za-z]{1,3}[0-9]{1,6}(:[A-Za-z]{1,3}[0-9]{1,6})?", cells or ""):
            raise g.GoogleError("diga o intervalo, ex. A2:F100")
        email = self._account(account, "sheets_escrever")
        rng = (f"'{tab}'!" if tab else "") + cells
        await self._write(email, "sheets_escrever", "POST", f"{g.SHEETS_API}/{sid}/values/{quote(rng, safe='')}:clear", {})
        return f"intervalo {cells} limpo (o histórico de versões da planilha guarda o que havia)"

    async def format_header(self, ref: str, tab: str = "", account: str = "") -> str:
        """Primeira linha em negrito e congelada."""
        sid = g.sheet_id(ref)
        email = self._account(account, "sheets_escrever")
        ids = await self._sheet_ids(email, sid)
        if not ids:
            raise g.GoogleError("planilha sem abas")
        if tab and tab not in ids:
            raise g.GoogleError(f"não existe a aba '{tab}'. Abas: {', '.join(ids)}")
        tid = ids[tab] if tab else next(iter(ids.values()))
        await self._write(email, "sheets_escrever", "POST", f"{g.SHEETS_API}/{sid}:batchUpdate", {"requests": [
            {"repeatCell": {"range": {"sheetId": tid, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}},
            {"updateSheetProperties": {"properties": {"sheetId": tid, "gridProperties": {"frozenRowCount": 1}},
                                       "fields": "gridProperties.frozenRowCount"}}]})
        return "cabeçalho em negrito e congelado"

    async def replace_in_doc(self, ref: str, find: str, replace: str, account: str = "") -> str:
        if not find:
            raise g.GoogleError("diga o texto a procurar")
        email = self._account(account, "docs_escrever")
        done = await self._write(email, "docs_escrever", "POST", f"{g.DOCS_API}/{g.file_id(ref)}:batchUpdate", {"requests": [
            {"replaceAllText": {"containsText": {"text": find[:500], "matchCase": True}, "replaceText": (replace or "")[:5000]}}]})
        n = (done.get("replies") or [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        return f"{n} trecho(s) substituído(s)"

    # --- Tarefas ----------------------------------------------------------------------------------------

    async def list_tasks(self, tasklist: str = "", account: str = "") -> str:
        if not tasklist:
            lists = await self._get(account, "tasks", f"{g.TASKS_API}/users/@me/lists")
            names = ", ".join(f"{x['title']} (id {x['id']})" for x in lists.get("items", []))
            return f"listas: {names}" if names else "nenhuma lista de tarefas"
        data = await self._get(account, "tasks", f"{g.TASKS_API}/lists/{_id(tasklist, 'id da lista')}/tasks", {"maxResults": 50})
        rows = [f"{'[x]' if t.get('status') == 'completed' else '[ ]'} {t.get('title', '')}"
                + (f" · até {t['due'][:10]}" if t.get("due") else "") + f" · id {t['id']}" for t in data.get("items", [])]
        return "\n".join(rows) or "nenhuma tarefa nessa lista"

    async def add_task(self, title: str, due: str = "", notes: str = "", tasklist: str = "@default", account: str = "") -> str:
        if not (title or "").strip():
            raise g.GoogleError("diga o título da tarefa")
        body: dict = {"title": title.strip()[:500]}
        if notes:
            body["notes"] = notes[:2000]
        if due:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                raise g.GoogleError("data inválida: use 2026-11-19")
            body["due"] = due + "T00:00:00.000Z"
        email = self._account(account, "tasks")
        await self._write(email, "tasks", "POST", f"{g.TASKS_API}/lists/{_id(tasklist, 'id da lista')}/tasks", body)
        return f"tarefa criada: {body['title']}"

    async def complete_task(self, task: str, tasklist: str = "@default", account: str = "") -> str:
        email = self._account(account, "tasks")
        await self._write(email, "tasks", "PATCH", f"{g.TASKS_API}/lists/{_id(tasklist, 'id da lista')}/tasks/{_id(task, 'id da tarefa')}",
                          {"status": "completed"})
        return "tarefa concluída"
