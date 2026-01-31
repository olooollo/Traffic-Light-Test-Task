from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Role(models.Model):
    name = models.CharField(max_length=255, unique=True)
    default_salary = models.IntegerField(validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name}"


class Department(models.Model):
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        help_text="Parent department for tree structure",
    )

    class Meta:
        verbose_name = "Department"
        verbose_name_plural = "Departments"
        ordering = ("id",)

    def __str__(self) -> str:
        return f"Department #{self.pk}" if self.pk is not None else "Department (unsaved)"

    def clean(self) -> None:
        super().clean()

        if self.parent_id is None or self.pk is None:
            if self.parent_id is not None and self.parent_id == self.pk:
                raise ValidationError({"parent": "A department cannot be its own parent."})
            return

        if self.parent_id == self.pk:
            raise ValidationError({"parent": "A department cannot be its own parent."})

        ancestor = self.parent
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise ValidationError({"parent": "Cycle detected in department hierarchy."})
            ancestor = ancestor.parent


class Employee(models.Model):
    full_name = models.CharField(max_length=255)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="employees")
    employment_date = models.DateTimeField(default=timezone.now)
    salary = models.IntegerField(validators=[MinValueValidator(0)])
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="employees",
        help_text="Department this employee belongs to.",
    )

    class Meta:
        verbose_name = "Employee"
        verbose_name_plural = "Employees"
        ordering = ("full_name", "id")
        indexes = [
            models.Index(fields=["department"]),
            models.Index(fields=["role"]),
            models.Index(fields=["employment_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name}"

    def clean(self) -> None:
        super().clean()

        if not self.full_name or not self.full_name.strip():
            raise ValidationError({"full_name": "Full name must not be empty."})

        if self.employment_date is None:
            raise ValidationError({"employment_date": "Employment date must be provided."})

        if self.role_id is None:
            raise ValidationError({"role": "Role must be provided."})

        role_default = getattr(self.role, "default_salary", None)
        if role_default is not None and self.salary < role_default:
            raise ValidationError(
                {"salary": f"Salary must be at least the role default salary ({role_default})."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

