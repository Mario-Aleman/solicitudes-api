from typing import Literal
from pydantic import BaseModel, Field

Tipo = Literal["Certificación", "Homologación", "Cancelación de materia", "Reintegro", "Otro"]
Estado = Literal["Pendiente", "En proceso", "Resuelta", "Rechazada"]


class SolicitudIn(BaseModel):
    estudiante: str = Field(min_length=3, max_length=100, examples=["Ana Pérez"])
    correo: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120, examples=["ana@correo.edu.co"])
    tipo: Tipo
    descripcion: str = Field(min_length=5, max_length=500)


class EstadoIn(BaseModel):
    estado: Estado
