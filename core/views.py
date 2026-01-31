from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import Department


BOOTSTRAP_CSS_CDN = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
BOOTSTRAP_JS_BUNDLE_CDN = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"


@dataclass(slots=True)
class DepartmentNode:
    id: int
    label: str
    children: List["DepartmentNode"] = field(default_factory=list)
    
    @property
    def has_children(self) -> bool:
        return bool(self.children)


def _build_department_tree(departments: Sequence[Department]) -> List[DepartmentNode]:
    node_by_id: Dict[int, DepartmentNode] = {}
    parent_by_id: Dict[int, Optional[int]] = {}

    for d in departments:
        if d.id is None:
            raise ValueError("Encountered Department without an id while building tree.")
        node_by_id[d.id] = DepartmentNode(id=d.id, label=f"{str(d)} [{d.employees.count()} employees]")
        parent_by_id[d.id] = d.parent_id

    roots: List[DepartmentNode] = []
    for dep_id, node in node_by_id.items():
        parent_id = parent_by_id[dep_id]
        if parent_id is None:
            roots.append(node)
        else:
            parent_node = node_by_id.get(parent_id)
            if parent_node is None:
                raise ValueError(f"Department {dep_id} references missing parent {parent_id}.")
            parent_node.children.append(node)

    def sort_rec(nodes: List[DepartmentNode]) -> None:
        nodes.sort(key=lambda n: n.id)
        for n in nodes:
            sort_rec(n.children)

    sort_rec(roots)
    return roots


@require_GET
def index(request: HttpRequest) -> HttpResponse:
    departments = list(Department.objects.all().only("id", "parent_id").order_by("id"))
    tree = _build_department_tree(departments)

    return render(
        request,
        "core/index.html",
        {
            "tree": tree,
            "bootstrap_css_cdn": BOOTSTRAP_CSS_CDN,
            "bootstrap_js_cdn": BOOTSTRAP_JS_BUNDLE_CDN,
        },
    )
