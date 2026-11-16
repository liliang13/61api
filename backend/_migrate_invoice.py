#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本:用户/管理端发票接口写入 api 文件"""
import io

# ---- api/user.py:发票接口 ----
f = 'api/user.py'
s = io.open(f, encoding='utf-8').read()
if 'def invoices' not in s:
    s = s.replace('from models import (ApiKey, InviteReward, ModelItem, RedemptionCode, TopupOrder, UsageLog, User)',
                  'from models import (ApiKey, Invoice, InvoiceItem, InviteReward, ModelItem, RedemptionCode, TopupOrder, UsageLog, User)')
    block = '''

# ---------------- 发票管理 ----------------

TAX_NO_RE = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")
EMAIL_RE = re.compile(r"^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")


def _invoiced_of(order_no: str) -> int:
    """订单已被(待开具/已开具)发票占用的金额。"""
    return (db.session.query(db.func.coalesce(db.func.sum(InvoiceItem.amount), 0))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(InvoiceItem.order_no == order_no,
                    Invoice.status.in_((0, 1))).scalar() or 0)


@bp.get("/invoices")
@auth_required
def invoices():
    rows = (Invoice.query.filter_by(user_id=g.user.id)
            .order_by(Invoice.id.desc()).limit(100).all())
    return ok([i.to_dict() for i in rows])


@bp.get("/invoices/available-orders")
@auth_required
def invoice_available_orders():
    """可开票的已支付订单:已支付、未退款、剩余可开额度 > 0。"""
    orders = (TopupOrder.query.filter_by(user_id=g.user.id, status="paid")
              .order_by(TopupOrder.id.desc()).limit(100).all())
    out = []
    for o in orders:
        left = o.amount - _invoiced_of(o.order_no)
        if left > 0:
            out.append({"order_no": o.order_no, "created_at": o.created_at.strftime("%Y-%m-%d") if o.created_at else "",
                        "amount": o.amount, "amount_yuan": o.amount / 100, "invoicable_yuan": left / 100})
    return ok(out)


@bp.post("/invoices")
@auth_required
def invoice_create():
    """提交开票申请:勾选已支付订单(按订单充值金额全额开票),多单可合并一张。"""
    data = request.get_json(silent=True) or {}
    order_nos = data.get("order_nos") or []
    inv_type = data.get("inv_type") or "电子普通发票"
    title_type = data.get("title_type") or "企业"
    title = (data.get("title") or "").strip()
    tax_no = (data.get("tax_no") or "").strip()
    email = (data.get("email") or "").strip()
    remark = (data.get("remark") or "").strip()[:200]

    if not order_nos:
        return err("请选择要开票的订单")
    if inv_type not in ("电子普通发票", "增值税专用发票"):
        return err("发票类型不正确")
    if title_type not in ("企业", "个人"):
        return err("抬头类型不正确")
    if not title:
        return err("请填写发票抬头")
    if title_type == "企业":
        if not TAX_NO_RE.match(tax_no):
            return err("税号格式不正确(18 位统一社会信用代码)")
    if not EMAIL_RE.match(email):
        return err("请填写正确的接收邮箱")

    total = 0
    picked = []
    for no in order_nos[:20]:
        o = TopupOrder.query.filter_by(order_no=no, user_id=g.user.id, status="paid").first()
        if not o:
            return err("订单不存在或状态不可开票: " + no)
        left = o.amount - _invoiced_of(o.order_no)
        if left <= 0:
            return err("订单 %s 已全额开票" % no)
        total += left
        picked.append((o, left))
    if total < 100:  # 最低开票 ¥1
        return err("开票金额最低 ¥1")

    inv = Invoice(user_id=g.user.id, amount=total, inv_type=inv_type,
                  title_type=title_type, title=title,
                  tax_no=tax_no if title_type == "企业" else "",
                  email=email, remark=remark)
    db.session.add(inv)
    db.session.flush()
    for o, amt in picked:
        db.session.add(InvoiceItem(invoice_id=inv.id, order_no=o.order_no,
                                   user_id=g.user.id, amount=amt))
    db.session.commit()
    return ok(inv.to_dict())


# ---------------- 发票管理结束 ----------------
'''
    s = s.rstrip() + block
    io.open(f, 'w', encoding='utf-8').write(s)
    print('user invoices ok')

# user.py 需要 import re
f = 'api/user.py'
s = io.open(f, encoding='utf-8').read()
if '\nimport re' not in s and 'import re\n' not in s.split('from')[0]:
    if s.startswith('#!/usr/bin/env python3'):
        lines = s.split('\n')
        for i, l in enumerate(lines):
            if l.startswith('import ') or l.startswith('from '):
                lines.insert(i, 'import re')
                break
        s = '\n'.join(lines)
io.open(f, 'w', encoding='utf-8').write(s)
print('re import ok')

# ---- admin.py:发票管理接口 + 退款拦截 ----
f = 'api/admin.py'
s = io.open(f, encoding='utf-8').read()
if 'InvoiceItem' not in s.split('from models import')[1].split('\n')[0] and 'InvoiceItem' not in s:
    m2 = re.search(r'from models import \(([^)]*)\)', s)
    if m2:
        if 'Invoice' not in m2.group(1):
            s = s.replace('from models import (', 'from models import (Invoice, InvoiceItem, ')
    else:
        m3 = re.search(r'from models import ([^\n(]+)\n', s)
        s = s.replace(m3.group(0), 'from models import Invoice, InvoiceItem, ' + m3.group(1)[18:] + '\n')

if '/invoices' not in s:
    anchor = '# ---------------- 邀请审计 ----------------'
    block = '''# ---------------- 发票管理 ----------------

@bp.get("/invoices")
@admin_required
def admin_invoices():
    page, size = page_args()
    q = Invoice.query
    status = request.args.get("status", type=int)
    if status is not None:
        q = q.filter(Invoice.status == status)
    total = q.count()
    rows = q.order_by(Invoice.id.desc()).offset((page - 1) * size).limit(size).all()
    items = []
    for i in rows:
        d = i.to_dict()
        u = db.session.get(User, i.user_id)
        d["username"] = u.username if u else "?"
        d["uid"] = u.uid if u else ""
        items.append(d)
    return ok({"total": total, "page": page, "page_size": size, "items": items})


@bp.put("/invoices/<int:iid>/issue")
@admin_required
def admin_invoice_issue(iid):
    """标记已开具(填写发票号)。"""
    inv = db.session.get(Invoice, iid)
    if not inv:
        return err("记录不存在", 404)
    if inv.status == 1:
        return err("已开具过")
    data = request.get_json(silent=True) or {}
    no = (data.get("invoice_no") or "").strip()
    if not no:
        return err("请填写发票号码")
    inv.status = 1
    inv.invoice_no = no[:64]
    inv.issued_at = datetime.now()
    db.session.commit()
    return ok()


@bp.put("/invoices/<int:iid>/reject")
@admin_required
def admin_invoice_reject(iid):
    """拒绝开票(额度随即释放,用户可重新申请)。"""
    inv = db.session.get(Invoice, iid)
    if not inv:
        return err("记录不存在", 404)
    if inv.status == 1:
        return err("已开具的发票不可拒绝,请走红冲流程")
    data = request.get_json(silent=True) or {}
    inv.status = 2
    inv.reject_reason = (data.get("reason") or "信息有误")[:200]
    db.session.commit()
    return ok()


# ---------------- 邀请审计 ----------------'''
    s = s.replace(anchor, block)

# 退款拦截:已开票订单不可退款
old_refund = '''    try:
        svc.refund_order(order_no, reason="管理员退款")
    except Exception as e:
        return err(str(e))
    return ok()'''
new_refund = '''    # 开票约束:已开票或开票申请中的订单不可退款(需先红冲/拒绝发票)
    used = (db.session.query(db.func.coalesce(db.func.sum(InvoiceItem.amount), 0))
            .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .filter(InvoiceItem.order_no == order_no,
                    Invoice.status.in_((0, 1))).scalar() or 0)
    if used > 0:
        return err("该订单已申请开票(¥%.2f),开票后不可退款。如需退款请先在发票管理中拒绝/红冲该发票。" % (used / 100))
    try:
        svc.refund_order(order_no, reason="管理员退款")
    except Exception as e:
        return err(str(e))
    return ok()'''
assert old_refund in s, 'refund pattern missing'
s = s.replace(old_refund, new_refund)
io.open(f, 'w', encoding='utf-8').write(s)
print('admin invoices + refund guard ok')