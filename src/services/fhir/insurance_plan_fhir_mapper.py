import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.coding import Coding
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.extension import Extension
from fhir.resources.extendedcontactdetail import ExtendedContactDetail
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.meta import Meta
from fhir.resources.narrative import Narrative
from fhir.resources.period import Period
from fhir.resources.quantity import Quantity
from fhir.resources.reference import Reference
from fhir.resources.organization import Organization
from fhir.resources.insuranceplan import (
    InsurancePlan,
    InsurancePlanCoverage,
    InsurancePlanCoverageBenefit,
    InsurancePlanCoverageBenefitLimit,
    InsurancePlanPlan,
    InsurancePlanPlanSpecificCost,
    InsurancePlanPlanSpecificCostBenefit,
    InsurancePlanPlanSpecificCostBenefitCost,
)
from pydantic import ValidationError

from src.services.fhir import fhir_constants as fhir_const
from src import constants
import os
import json

logger = logging.getLogger(__name__)

SNOMED_DICT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "snomed_dictionary.json")
SNOMED_DICT = {}
TERM_TO_CODE = {}
try:
    with open(SNOMED_DICT_PATH, "r") as f:
        SNOMED_DICT = json.load(f)
        TERM_TO_CODE = SNOMED_DICT.get("termToCodeMapping", {})
except FileNotFoundError:
    logger.warning(constants.LOG_FHIR_SNOMED_NOT_FOUND)


def _make_coding(
    code: Optional[str] = None,
    display: Optional[str] = None,
    system: Optional[str] = None,
) -> Coding:
    kwargs: Dict[str, Any] = {}
    if system:
        kwargs["system"] = system
    if code:
        kwargs["code"] = code
    if display:
        kwargs["display"] = display
    return Coding(**kwargs)


def _make_concept(
    code: Optional[str] = None,
    display: Optional[str] = None,
    system: Optional[str] = None,
    text: Optional[str] = None,
) -> CodeableConcept:
    kwargs: Dict[str, Any] = {
        "coding": [_make_coding(code=code, display=display, system=system)]
    }
    if text:
        kwargs["text"] = text
    return CodeableConcept(**kwargs)


def _make_narrative(text_summary: str, status: str = "generated") -> Narrative:
    safe = text_summary.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    div = f'<div xmlns="http://www.w3.org/1999/xhtml"><p>{safe}</p></div>'
    return Narrative(status=status, div=div)


class InsurancePlanFHIRMapper:

    def __init__(self, extracted_data: Dict[str, Any]):
        self.data: Dict[str, Any] = extracted_data or {}
        self.bundle = Bundle(
            id=str(uuid.uuid4()),
            type=fhir_const.BUNDLE_TYPE_COLLECTION,
            language=fhir_const.LANGUAGE_EN_IN,
            timestamp=datetime.now(timezone.utc),
            entry=[],
        )

    def _add_to_bundle(self, resource) -> None:
        entry = BundleEntry(
            fullUrl=f"urn:uuid:{resource.id}",
            resource=resource,
        )
        if self.bundle.entry is None:
            self.bundle.entry = []
        self.bundle.entry.append(entry)

    def _get(self, data: Dict[str, Any], key: str, fallback: Any = None) -> Any:
        value = data.get(key)
        if value is None or str(value).strip() == "":
            return fallback
        return value

    def _require(self, data: Dict[str, Any], key: str, context: str, fallback: str = "Unknown") -> Any:
        value = self._get(data, key)
        if value is None:
            logger.warning(constants.LOG_FHIR_MISSING_REQUIRED_FIELD, key, context, fallback)
            return fallback
        return value

    def _parse_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(constants.LOG_FHIR_FLOAT_PARSE_FAILED.format(value=value, default=default))
            return default

    def _lookup_snomed_code(self, provided_code: Optional[str], display_text: Optional[str]) -> Optional[str]:
        s_code = str(provided_code).strip() if provided_code else ""
        if s_code and s_code.isdigit() and len(s_code) > 5:
            return s_code
        s_display = str(display_text).strip().lower() if display_text else ""
        if s_display and s_display in TERM_TO_CODE:
            return TERM_TO_CODE[s_display]
        return provided_code

    def _build_organization(
        self,
        org_data: Optional[Dict[str, Any]],
        is_tpa: bool = False,
    ) -> Optional[str]:
        if not org_data:
            return None
        try:
            org_id = str(uuid.uuid4())
            org = Organization(
                id=org_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_ORGANIZATION]),
                name=self._require(org_data, "name", "organisation"),
            )

            identifier_value = self._get(org_data, "identifier")
            id_system = fhir_const.SYS_IRDAI_IDENTIFIER if is_tpa else fhir_const.SYS_INSURER_IDENTIFIER
            identifiers = []
            if identifier_value:
                identifiers.append(
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=id_system,
                        value=str(identifier_value).strip(),
                    )
                )
            else:
                identifiers.append(
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=id_system,
                        value=f"urn:uuid:{uuid.uuid4()}",
                    )
                )
            org.identifier = identifiers

            telecom_entries: List[ContactPoint] = []
            phone = self._get(org_data, "phone")
            if phone:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_PHONE, value=str(phone).strip()))
            email = self._get(org_data, "email")
            if email:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_EMAIL, value=str(email).strip()))
            website = self._get(org_data, "website")
            if website:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_URL, value=str(website).strip()))
            if telecom_entries:
                org.contact = [ExtendedContactDetail(telecom=telecom_entries)]

            self._add_to_bundle(org)
            return f"urn:uuid:{org_id}"

        except ValidationError as e:
            ctx = constants.FHIR_ORG_CONTEXT_TPA if is_tpa else constants.FHIR_ORG_CONTEXT_INSURER
            logger.error(constants.LOG_FHIR_SKIP_ORG_VALIDATION, ctx, e)
            return None

    def _build_networks(self, networks_data: List[str]) -> List[Reference]:
        refs: List[Reference] = []
        for network_name in (networks_data or []):
            if not network_name or not str(network_name).strip():
                continue
            net_id = str(uuid.uuid4())
            network_org = Organization(
                id=net_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_ORGANIZATION]),
                name=str(network_name).strip(),
                type=[_make_concept(
                    code="prov",
                    display="Healthcare Provider Network",
                    system="http://terminology.hl7.org/CodeSystem/organization-type",
                )],
            )
            self._add_to_bundle(network_org)
            refs.append(Reference(reference=f"urn:uuid:{net_id}", display=str(network_name).strip()))
        return refs

    def _build_complex_extension(self, url: str, sub_extensions: List[Extension]) -> Extension:
        return Extension(url=url, extension=sub_extensions)

    def _build_contacts(self, contacts_data: List[Dict[str, Any]]) -> List[ExtendedContactDetail]:
        contacts: List[ExtendedContactDetail] = []
        for cd in (contacts_data or []):
            kwargs: Dict[str, Any] = {}
            purpose_text = self._get(cd, "purpose")
            if purpose_text:
                kwargs["purpose"] = _make_concept(
                    code=purpose_text,
                    display=purpose_text,
                    system=fhir_const.CONTACT_PURPOSE_SYSTEM,
                    text=purpose_text,
                )
            contact_name = self._get(cd, "name")
            if contact_name:
                kwargs["name"] = [HumanName(text=str(contact_name))]
            telecom_entries: List[ContactPoint] = []
            phone = self._get(cd, "phone")
            if phone:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_PHONE, value=str(phone)))
            email = self._get(cd, "email")
            if email:
                telecom_entries.append(ContactPoint(system=fhir_const.TELECOM_SYSTEM_EMAIL, value=str(email)))
            if telecom_entries:
                kwargs["telecom"] = telecom_entries
            if kwargs:
                contacts.append(ExtendedContactDetail(**kwargs))
        return contacts

    def _build_coverage_areas(self, areas_data: List[str]) -> List[Reference]:
        return [Reference(display=area) for area in (areas_data or []) if area]

    def _build_plan_extensions(self, plan_data: Dict[str, Any]) -> List[Extension]:
        extensions: List[Extension] = []
        for req in (plan_data.get("supportingInfoRequirements") or []):
            ext = self._build_complex_extension(
                fhir_const.EXT_SUPPORTING_INFO_REQ,
                [
                    Extension(
                        url="category",
                        valueCodeableConcept=_make_concept(
                            code=self._get(req, "categoryCode"),
                            display=self._get(req, "categoryDisplay"),
                        ),
                    ),
                    Extension(
                        url="document",
                        valueCodeableConcept=_make_concept(
                            code=self._get(req, "documentCode"),
                            display=self._get(req, "documentDisplay"),
                        ),
                    ),
                ],
            )
            extensions.append(ext)

        for excl in (plan_data.get("exclusions") or []):
            sub: List[Extension] = [
                Extension(
                    url="category",
                    valueCodeableConcept=_make_concept(
                        code=self._get(excl, "categoryCode"),
                        display=self._get(excl, "categoryDisplay"),
                    ),
                ),
            ]
            statement = self._get(excl, "statement")
            if statement:
                sub.append(Extension(url="statement", valueString=statement))
            extensions.append(self._build_complex_extension(fhir_const.EXT_EXCLUSION, sub))

        return extensions

    def _build_benefit_block(self, ben_data: Dict[str, Any]) -> InsurancePlanCoverageBenefit:
        raw_code = self._get(ben_data, "typeCode")
        display_text = self._get(ben_data, "typeDisplay")
        final_code = self._lookup_snomed_code(raw_code, display_text)
        system = fhir_const.SYS_SNOMED if (final_code and str(final_code).isdigit()) else None

        benefit = InsurancePlanCoverageBenefit(
            type=_make_concept(code=final_code, display=display_text, system=system)
        )

        limit_value = self._get(ben_data, "limitValue")
        if limit_value is not None:
            limit_unit = self._get(ben_data, "limitUnit")
            safe_value = self._parse_float(limit_value)
            limit_quantity = Quantity(value=safe_value, unit=limit_unit)
            limit_code = InsurancePlanCoverageBenefitLimit(
                value=limit_quantity,
                code=_make_concept(
                    code="benefit",
                    display=f"{limit_value} {limit_unit or ''}".strip(),
                    system="http://terminology.hl7.org/CodeSystem/benefit-unit",
                ),
            )
            benefit.limit = [limit_code]

        return benefit

    def _build_coverages(self, coverages_data: List[Dict[str, Any]]) -> List[InsurancePlanCoverage]:
        coverages: List[InsurancePlanCoverage] = []
        for cov_data in (coverages_data or []):
            coverage = InsurancePlanCoverage(
                type=_make_concept(display=self._get(cov_data, "typeDisplay")),
                benefit=[
                    self._build_benefit_block(ben)
                    for ben in (cov_data.get("benefits") or [])
                ],
            )
            condition = self._get(cov_data, "condition")
            if condition:
                coverage.extension = [
                    self._build_complex_extension(
                        fhir_const.EXT_CONDITION,
                        [Extension(url="statement", valueString=condition)],
                    )
                ]
            coverages.append(coverage)
        return coverages

    def _build_specific_cost_block(self, cost_data: Dict[str, Any]) -> Optional[InsurancePlanPlanSpecificCost]:
        try:
            cost_value_raw = self._require(cost_data, "costValue", "specificCost.cost")
            cost_type_code = self._require(cost_data, "costType", "specificCost.cost")
            cost_unit = self._require(cost_data, "costUnit", "specificCost.cost")

            applicability_map = {
                "copay": fhir_const.APPLICABILITY_IN_NETWORK,
                "deductible": fhir_const.APPLICABILITY_IN_NETWORK,
                "fullcoverage": fhir_const.APPLICABILITY_IN_NETWORK,
                "out-of-network": fhir_const.APPLICABILITY_OUT_OF_NETWORK,
            }
            applicability_code = applicability_map.get(
                str(cost_type_code).lower(), fhir_const.APPLICABILITY_OTHER
            )

            benefit_cost = InsurancePlanPlanSpecificCostBenefitCost(
                type=_make_concept(
                    code=cost_type_code,
                    system="http://terminology.hl7.org/CodeSystem/benefit-cost-type",
                ),
                applicability=_make_concept(
                    code=applicability_code,
                    display=applicability_code.replace("-", " ").title(),
                    system=fhir_const.VS_COST_APPLICABILITY,
                ),
                value=Quantity(value=self._parse_float(cost_value_raw), unit=cost_unit),
            )

            raw_ben_code = self._require(cost_data, "benefitTypeCode", "specificCost.benefit")
            display_ben_text = self._get(cost_data, "benefitTypeDisplay")
            final_ben_code = self._lookup_snomed_code(raw_ben_code, display_ben_text)
            sys_ben = fhir_const.SYS_SNOMED if (final_ben_code and str(final_ben_code).isdigit()) else None

            benefit = InsurancePlanPlanSpecificCostBenefit(
                type=_make_concept(code=final_ben_code, display=display_ben_text, system=sys_ben),
                cost=[benefit_cost],
            )

            raw_cat_code = self._require(cost_data, "categoryCode", "specificCost")
            display_cat_text = self._get(cost_data, "categoryDisplay")
            final_cat_code = self._lookup_snomed_code(raw_cat_code, display_cat_text)
            sys_cat = fhir_const.SYS_SNOMED if (final_cat_code and str(final_cat_code).isdigit()) else None

            return InsurancePlanPlanSpecificCost(
                category=_make_concept(code=final_cat_code, display=display_cat_text, system=sys_cat),
                benefit=[benefit],
            )

        except (ValidationError, ValueError, TypeError) as e:
            logger.warning(constants.LOG_FHIR_SKIP_COST_BLOCK, e)
            return None

    def _build_financial_plans(self, plans_data: List[Dict[str, Any]]) -> List[InsurancePlanPlan]:
        plans: List[InsurancePlanPlan] = []
        for plan_data in (plans_data or []):
            plan = InsurancePlanPlan(
                identifier=[
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=fhir_const.SYS_IDENTIFIER,
                        value=f"urn:uuid:{uuid.uuid4()}",
                    )
                ],
                type=_make_concept(
                    code=self._get(plan_data, "planTypeCode"),
                    display=self._get(plan_data, "planTypeDisplay"),
                    system=fhir_const.VS_PLAN_TYPE,
                ),
            )
            specific_costs = [
                cost_block
                for cost_data in (plan_data.get("specificCosts") or [])
                if (cost_block := self._build_specific_cost_block(cost_data)) is not None
            ]
            if specific_costs:
                plan.specificCost = specific_costs
            plans.append(plan)
        return plans

    def _build_insurance_plan(
        self,
        plan_data: Optional[Dict[str, Any]],
        owned_by_ref: str,
        admin_by_ref: Optional[str] = None,
        network_refs: Optional[List[Reference]] = None,
    ) -> None:
        if not plan_data:
            return
        try:
            plan_id = str(uuid.uuid4())
            plan_name = self._require(plan_data, "name", "insurancePlan")

            insurance_plan = InsurancePlan(
                id=plan_id,
                meta=Meta(profile=[fhir_const.META_PROFILE_INSURANCE_PLAN]),
                text=_make_narrative(
                    f"Insurance Plan: {plan_name}. "
                    f"Status: {plan_data.get('status', 'active')}."
                ),
                language=self._get(plan_data, "language", fhir_const.LANGUAGE_EN_IN),
                status=self._get(plan_data, "status", "active"),
                name=plan_name,
                alias=[a for a in (plan_data.get("alias") or []) if a],
                identifier=[
                    Identifier(
                        use=fhir_const.IDENTIFIER_USE_OFFICIAL,
                        system=fhir_const.SYS_IDENTIFIER,
                        value=f"urn:uuid:{uuid.uuid4()}",
                    )
                ],
                type=[
                    _make_concept(
                        code=self._require(plan_data, "typeCode", "insurancePlan.type"),
                        display=self._get(plan_data, "typeDisplay"),
                        system=fhir_const.VS_INSURANCE_PLAN_TYPE,
                    )
                ],
                ownedBy=Reference(reference=owned_by_ref),
            )

            if admin_by_ref:
                insurance_plan.administeredBy = Reference(reference=admin_by_ref)

            period_start = self._get(plan_data, "periodStart")
            period_end = self._get(plan_data, "periodEnd")
            if period_start or period_end:
                insurance_plan.period = Period(start=period_start, end=period_end)

            if network_refs:
                insurance_plan.network = network_refs

            contacts = self._build_contacts(plan_data.get("contacts") or [])
            if contacts:
                insurance_plan.contact = contacts

            coverage_areas = self._build_coverage_areas(plan_data.get("coverageArea") or [])
            if coverage_areas:
                insurance_plan.coverageArea = coverage_areas

            extensions = self._build_plan_extensions(plan_data)
            if extensions:
                insurance_plan.extension = extensions

            coverages = self._build_coverages(plan_data.get("coverages") or [])
            if coverages:
                insurance_plan.coverage = coverages

            plans = self._build_financial_plans(plan_data.get("plans") or [])
            if plans:
                insurance_plan.plan = plans

            self._add_to_bundle(insurance_plan)

        except ValidationError as e:
            logger.error(constants.LOG_FHIR_SKIP_INSURANCE_PLAN, e)

    def generate_dict(self) -> Dict[str, Any]:
        org_data = self.data.get("organisation") or self.data.get("organization") or {}
        owned_by_ref = self._build_organization(org_data)
        admin_by_ref = self._build_organization(self.data.get("tpaOrganisation"), is_tpa=True)

        plan_data = self.data.get("insurancePlan") or {}
        network_refs = self._build_networks(plan_data.get("networks") or [])

        if owned_by_ref:
            self._build_insurance_plan(plan_data, owned_by_ref, admin_by_ref, network_refs)
        else:
            logger.error(constants.LOG_FHIR_OWNED_BY_NONE)

        if self.bundle.entry:
            ip_index = next(
                (i for i, entry in enumerate(self.bundle.entry)
                 if getattr(entry.resource, "__resource_type__", None) == "InsurancePlan"),
                -1
            )
            if ip_index > 0:
                ip_entry = self.bundle.entry.pop(ip_index)
                self.bundle.entry.insert(0, ip_entry)

        return self.bundle.model_dump(mode="json", exclude_none=True)
