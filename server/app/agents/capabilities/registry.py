"""Only a server-owned approval manifest can register executable capabilities.

SKILL.md is instruction data, not an installation mechanism or a permission grant.
Listing a skill reads front matter only. Bodies/resources are loaded after selection.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from app.core.errors import AppError
from app.agents.capabilities.contracts import CapabilityManifest, ExecutionContext, Empty, ImageRequest, LibrarySearch


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def permitted(approval, ctx):
    return (approval.enabled and ctx.organization_id in approval.organizations
            and (not approval.users or ctx.user_id in approval.users))


def skill_metadata(path):
    import yaml
    try:
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("size")
        with path.open(encoding="utf-8-sig") as stream:
            if stream.readline().strip() != "---":
                raise ValueError("front matter")
            header, closed, size = [], False, 0
            for line in stream:
                if line.strip() == "---":
                    closed = True
                    break
                size += len(line)
                if size > 4096:
                    raise ValueError("metadata size")
                header.append(line)
            if not closed:
                raise ValueError("front matter end")
        return yaml.safe_load("".join(header))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        raise AppError("agent.skill_invalid", "获准SKILL.md不存在、过大或元数据格式无效。", 503) from None


@dataclass(frozen=True)
class Capability:
    id: str
    description: str
    version: str
    source: str
    permissions: tuple[str, ...]
    input_schema: dict
    keywords: tuple[str, ...] = ()
    risk: str = "read_only"
    may_charge: bool = False
    binding: str | None = None
    ready: bool = True
    blocked_reason: str | None = None

    def summary(self):
        return {"id": self.id, "description": self.description, "version": self.version,
                "source": self.source, "risk": self.risk, "may_charge": self.may_charge,
                "ready": self.ready, "blocked_reason": self.blocked_reason,
                "permissions": list(self.permissions)}


class BusinessToolRegistry:
    """Expose the existing registry, not another implementation of business actions."""
    @staticmethod
    def list(ctx):
        from app.agents.tool_registry import TOOLS
        from app.agents.production import AnalyzeAssets, PlanAction
        from app.agents.amazon_contracts import SavePlan, ModuleRevision, ModuleRevisions, GenerateAPlus
        descriptions = {
            'guide_batch_inputs':('在聊天内引导上传模板和服装，返回上传引导卡，不生成图片',('开始','批量换衣','上传')),
            'recall_user_experience':('按当前用户及商品场景检索已确认偏好和成功案例',('偏好','记忆','以前','风格','经验')),
            'manage_user_preference':('根据用户明确的以后/记住/忘记表达更新个人偏好，不能改写商品事实',('记住','以后','忘记','不用记','偏好','不要使用之前')),
            'configure_batch_inputs':('根据用户要求纠正素材角色、所属逻辑服装以及一一对应或指定组合，expected_revision来自当前清单',('一一对应','分组','正面','背面','字体','关联','组合','衣服','模特')),
            "read_business_context": ("读取当前项目素材和业务状态", ("素材", "项目", "context")),
            "read_jobs": ("读取本会话任务状态", ("进度", "任务", "status")),
            "read_shared_queue": ("读取同组织全员队列摘要，不返回其他人的图片", ("队列", "排队", "queue")),
            "export_results": ("获取已授权批次的下载入口", ("下载", "导出", "export")),
            "prepare_tryon_workspace": ("仅应用户要求打开专业工作台时关联已有素材，不是聊天批量换衣的前置步骤", ("打开工作台", "专业工作台")),
            "compile_prompt_plan": ("复用现有Prompt Composer进行组合预览", ("提示词", "编译")),
        }
        result = [Capability("business.create_images", "生成或编辑图片；多张各自换背景/修改时edit=true、independent_edits=true，每张原图独立Job；不是拼图、换衣矩阵或多图融合",
            "2", "business", ("jobs.submit", "projects.write", "assets.read"), ImageRequest.model_json_schema(),
            ("生成", "图片", "背景", "修改", "编辑", "image", "create"), "write", True, "generate_chat_images"),
            Capability("business.search_my_assets", "搜索本人素材库，返回Asset元数据，不跨账号共享", "1", "business",
                ("assets.read",), LibrarySearch.model_json_schema(), ("素材", "搜索", "查找", "参考图", "library")),
            Capability("business.current_context", "读取当前会话已授权素材与图片版本，不要求先有项目", "1", "business",
                ("assets.read",), Empty.model_json_schema(), ("参考", "素材", "版本", "当前")),
            Capability("business.current_jobs", "查询当前会话的真实任务进度，不接受其他会话的任务ID", "1", "business",
                ("jobs.read",), Empty.model_json_schema(), ("进度", "任务状态", "progress")),
            Capability("business.analyze_assets", "默认template_first：每模板规划一份通用换衣Prompt，已确定服装直接作参考、不逐件识别；仅未知角色补充分类。用户明确要求逐图精细时才用per_asset。复用模板规划缓存", "3", "business",
                ("jobs.submit","assets.read"),AnalyzeAssets.model_json_schema(),("识别","批量","模板","服装","套图"),'write',True,'analyze_chat_assets'),
            Capability("business.generate_tryon", "根据聊天素材清单编译Prompt并提交原B路径；默认validation每模板一张样图，审核后可按approved_only分批production", "3", "business",
                ("jobs.submit","projects.write","assets.read"),PlanAction.model_json_schema(),("样图","批量","套图","全部生成"),'write',True,'generate_chat_tryon')]
        from app.agents.batch_followup import BatchFollowup
        from app.agents.samples import ReviewSamples
        result.append(Capability('business.review_tryon_samples','依据用户样图编号及Output ID批量通过、修改或重做；禁止Agent自行通过样图','1','business',
            ('batch_tryon.review','assets.read'),ReviewSamples.model_json_schema(),('通过','样图','太暗','号码错误','重做','修改'),'write',True,'review_tryon_samples'))
        result.append(Capability('business.followup_batch_results','按真实方案ID与模板序号，只调整对应结果或仅重试明确失败的组合，不重做其他成功项；复用原审核版本服务','1','business',
            ('jobs.submit','assets.read','projects.write','batch_tryon.review'),BatchFollowup.model_json_schema(),('模板','调整','偏暗','失败','重试','换衣'),'write',True,'followup_batch_results'))
        result.extend([
            Capability('business.amazon_context', '读取本会话A+方案、市场证据和版本化模块规则，不进行外部查询', '1', 'business',
                ('assets.read',), Empty.model_json_schema(), ('Amazon','亚马逊','A+','ASIN','模块','运营')),
            Capability('business.save_aplus_plan', '保存整套Amazon A+或Listing图片方案；Listing按六类方向自由设计，非固定六张。保存后一次方案确认或按用户直接生成要求生产。', '2','business',
                ('projects.write','assets.read'), SavePlan.model_json_schema(), ('A+','亚马逊','策划','运营'), 'write',False,'save_aplus_plan'),
            Capability('business.revise_aplus_module', '只调整指定稳定ID的A+模块，保留其他模块及旧结果，取消该模块确认', '1','business',
                ('projects.write','assets.read'), ModuleRevision.model_json_schema(), ('A+','第三','模块','修改'), 'write',False,'revise_aplus_module'),
            Capability('business.revise_amazon_modules', '原子修改用户指出的多个图片模块，保持其余模块及旧Output不变；按方案内稳定ID，不用聊天全局编号猜测。', '1','business',
                ('projects.write','assets.read'), ModuleRevisions.model_json_schema(), ('A+','Listing','附图','第二','第四','修改'), 'write',False,'revise_amazon_modules'),
            Capability('business.generate_aplus', '仅为已人工确认的指定A+模块报价并提交原A+生成队列', '1','business',
                ('jobs.submit','projects.write','assets.read'),GenerateAPlus.model_json_schema(),('A+','模块','生成','亚马逊'),'write',True,'generate_aplus'),
        ])
        for name, (description, keywords) in descriptions.items():
            spec = TOOLS[name]
            result.append(Capability("business."+name, description, "1", "business", spec.permissions,
                spec.schema.model_json_schema(), keywords, "write" if spec.writes else "read_only", spec.model_cost, name))
        # Hermes remains the authority for attachment operations. Only its implemented read context is exposed here.
        from app.services.hermes_tool_registry import TOOL_INDEX
        from app.agents.contracts import ContextRead
        for name in ("get_workbench_context", "get_product_context"):
            spec = TOOL_INDEX[name]
            result.append(Capability("hermes."+name, spec.description, "1", "hermes", (spec.required_permission,),
                ContextRead.model_json_schema(), ("附图", "商品", "A+", "上下文"), binding="read_business_context"))
        return [c for c in result if set(c.permissions) <= ctx.permissions]


class SkillRegistry:
    def __init__(self, root, approvals, ctx):
        self.root, self.approvals, self.ctx = root, approvals, ctx
        self._entries = {}

    def catalog(self):
        result = []
        for approval in self.approvals:
            if not permitted(approval, self.ctx) or not set(approval.permissions) <= self.ctx.permissions:
                continue
            path = (self.root / approval.path).resolve()
            if not path.is_relative_to(self.root.resolve()) or path.name != "SKILL.md":
                raise AppError("agent.skill_invalid", "Skill路径或大小未通过安全检查。", 503)
            meta = skill_metadata(path)
            if not isinstance(meta, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,70}", str(meta.get("name", ""))):
                raise AppError("agent.skill_invalid", "Skill名称不合法。", 503)
            key = meta["name"]
            if key in self._entries:
                raise AppError("agent.skill_conflict", "存在重名Skill，请指定唯一版本。", 503)
            entry = {"id": key, "version": approval.version, "description": str(meta.get("description", ""))[:600],
                "allowed_tools": approval.allowed_tools, "keywords": approval.keywords}
            result.append(entry)
            self._entries[key] = (path, approval, entry)
        return result

    def load(self, key):
        if key not in self._entries:
            raise AppError("agent.skill_not_allowed", "Skill未注册、已停用或无权访问。", 403)
        path, approval, entry = self._entries[key]
        body = path.read_text(encoding="utf-8-sig")
        return {**entry, "body": body, "content_hash": hashlib.sha256(body.encode()).hexdigest(),
                "trust": "approved_skill_guidance_not_system_policy"}

    def resource(self, key, relative_path):
        if key not in self._entries:
            raise AppError("agent.skill_not_allowed", "Skill不可访问。", 403)
        folder = self._entries[key][0].parent.resolve()
        path = (folder / relative_path).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or path.stat().st_size > 32768 or path.suffix not in {".md", ".txt", ".json"}:
            raise AppError("agent.skill_resource_denied", "该Skill资源不可加载或不是文本资源。", 403)
        return path.read_text(encoding="utf-8-sig")


class CapabilityRegistry:
    def __init__(self, settings, ctx: ExecutionContext):
        self.ctx, self.settings = ctx, settings
        builtin = Path(__file__).resolve().parent / "skills"
        manifest = CapabilityManifest()
        root = builtin
        if settings.agent_capability_manifest:
            path = Path(settings.agent_capability_manifest).resolve()
            try:
                if path.stat().st_size > 131072:
                    raise ValueError("size")
                manifest = CapabilityManifest.model_validate(json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError):
                raise AppError("agent.registry_invalid", "能力审批配置不可读取或校验失败；不会降级加载未批准工具。", 503) from None
            root = path.parent
        from app.agents.capabilities.contracts import SkillApproval
        defaults = [SkillApproval(path=name+"/SKILL.md", version="2" if name in {'amazon-aplus-planner','amazon-visual-brief'} else "1", enabled=True, approved_by="application-release",
            organizations=[ctx.organization_id], permissions=["jobs.read"], allowed_tools=tools, keywords=keywords)
            for name, tools, keywords in (
                ("image-creation", ["business.current_context", "business.create_images","business.recall_user_experience","business.manage_user_preference"], ["生成", "修改", "编辑", "换成", "替换", "生图", "展示图", "背景", "image","偏好","记住","以后","忘记"]),
                ("asset-search", ["business.search_my_assets", "business.current_context"], ["素材", "搜索", "查找"]),
                ("queue-inspection", ["business.read_shared_queue", "business.current_jobs"], ["队列", "进度", "排队"]),
                ("batch-production", ["business.analyze_assets","business.generate_tryon","business.configure_batch_inputs","business.followup_batch_results","business.current_context","business.guide_batch_inputs","business.review_tryon_samples","business.recall_user_experience","business.manage_user_preference"], ["批量","模板","服装","套图","换衣","衣服","模特","样图","通过","重做"]),
                ('amazon-market-insight', ['business.amazon_context'], ['Amazon','亚马逊','ASIN','竞品','VOC','关键词','市场','Review']),
                ('amazon-aplus-planner', ['business.amazon_context','business.save_aplus_plan','business.revise_aplus_module','business.revise_amazon_modules'], ['Amazon','亚马逊','A+','运营','策划','模块','Listing','附图']),
                ('amazon-visual-brief', ['business.amazon_context','business.generate_aplus'], ['Amazon','亚马逊','A+','运营','生成','模块']),
            )]
        builtins = SkillRegistry(builtin, defaults, ctx)
        self.skills = SkillRegistry(root, manifest.skills, ctx)
        self.skill_catalog = builtins.catalog()+self.skills.catalog()
        if len({s["id"] for s in self.skill_catalog}) != len(self.skill_catalog):
            raise AppError("agent.skill_conflict", "自定义Skill不得覆盖系统Skill名称。", 503)
        self._builtins = builtins
        self.mcp = {s.id: s for s in manifest.mcp_servers if permitted(s, ctx)}
        self.capabilities = {c.id: c for c in BusinessToolRegistry.list(ctx)}
        for server in self.mcp.values():
            for tool in server.tools:
                if server.profile == 'sellersprite':
                    from app.agents.amazon_research import ALLOWED_TOOLS
                    if tool.name not in ALLOWED_TOOLS:
                        raise AppError('agent.mcp_tool_not_allowed','卖家精灵首期只允许六项只读工具。',503)
                    if not tool.may_charge or tool.risk!='read_only':
                        raise AppError('agent.mcp_cost_policy','卖家精灵业务查询必须按可能收费的只读工具审批。',503)
                if not set(tool.permissions) <= ctx.permissions:
                    continue
                ready = tool.risk == "read_only" and not tool.may_charge
                if server.profile=='sellersprite' and tool.risk=='read_only' and tool.max_charge_units is not None:
                    ready=True
                cap = Capability(f"mcp.{server.id}.{tool.name}", tool.description, server.version, "mcp",
                    tuple(tool.permissions), tool.input_schema, tuple(tool.keywords), tool.risk, tool.may_charge,
                    server.id, ready, None if ready else "agent.mcp_risk_not_enabled")
                if cap.id in self.capabilities:
                    raise AppError("agent.capability_conflict", "能力名称重复。", 503)
                self.capabilities[cap.id] = cap

    def get(self, key):
        cap = self.capabilities.get(key)
        if not cap or not set(cap.permissions) <= self.ctx.permissions or not cap.ready:
            raise AppError("agent.capability_not_allowed", "该能力未授权、未就绪或当前账号无权限。", 403)
        return cap

    def load_skill(self, key):
        registry = self._builtins if key in self._builtins._entries else self.skills
        return registry.load(key)

    def snapshot(self):
        return digest({"tools": [{**c.summary(), "schema": c.input_schema} for c in self.capabilities.values()],
                       "skills": [{k: s[k] for k in ("id", "version", "allowed_tools")} for s in self.skill_catalog],
                       "approval": {k: v.model_dump() for k, v in self.mcp.items()}})


class ToolSelector:
    """Relevance selection is a candidate filter, not an intent-to-workflow switch."""
    @staticmethod
    def select(registry, goal, *, extra_ids=(),primary_skills=()):
        def score(description, keywords):
            return sum(2 for word in keywords if word.lower() in goal.lower()) + int(goal.lower() in description.lower())
        skills = sorted(registry.skill_catalog, key=lambda s: score(s["description"], s["keywords"]), reverse=True)
        pinned=[s for key in primary_skills for s in registry.skill_catalog if s['id']==key]
        skills=pinned+[s for s in skills if s['id'] not in primary_skills and score(s["description"],s['keywords'])][:3]
        primary_tools={t for s in pinned for t in s['allowed_tools']}
        # Keep a small general entry set for goals whose wording has no keyword overlap.
        # The actual tool decision is made by the structured planner, not this ranker.
        preferred = {t for s in skills for t in s["allowed_tools"]} | set(extra_ids) | {
            "business.create_images", "business.current_context", "business.search_my_assets"}
        candidates = sorted([c for c in registry.capabilities.values() if c.ready],
            key=lambda c: (c.id in primary_tools,c.id in preferred, score(c.description, c.keywords)), reverse=True)
        selected = [c for c in candidates if c.id in preferred or score(c.description, c.keywords)][:12]
        return {"skills": skills, "tools": [{**c.summary(), "input_schema": c.input_schema} for c in selected],
                "catalog_version": registry.snapshot()}
