import numpy as np
import pytest

from gdml_geometry import PlacedMesh, parse_gdml_bytes

B1_LIKE = b"""<?xml version="1.0"?>
<gdml>
  <materials>
    <material name="Nothing" Z="1"><D value="1e-25"/><atom value="1.008"/></material>
  </materials>
  <solids>
    <box name="World" x="400" y="400" z="400" lunit="mm"/>
    <cone name="Shape1" rmin1="0" rmax1="20" rmin2="0" rmax2="40" z="60"
          startphi="0" deltaphi="360" aunit="deg" lunit="mm"/>
    <trd name="Shape2" x1="120" x2="120" y1="100" y2="160" z="60" lunit="mm"/>
  </solids>
  <structure>
    <volume name="Shape1LV">
      <materialref ref="Nothing"/><solidref ref="Shape1"/>
    </volume>
    <volume name="Shape2LV">
      <materialref ref="Nothing"/><solidref ref="Shape2"/>
    </volume>
    <volume name="WorldLV">
      <materialref ref="Nothing"/><solidref ref="World"/>
      <physvol name="Shape1">
        <volumeref ref="Shape1LV"/>
        <position name="p1" x="0" y="20" z="-70" unit="mm"/>
      </physvol>
      <physvol name="Shape2">
        <volumeref ref="Shape2LV"/>
        <position name="p2" x="0" y="-10" z="70" unit="mm"/>
      </physvol>
    </volume>
  </structure>
  <setup name="Default" version="1.0"><world ref="WorldLV"/></setup>
</gdml>
"""


@pytest.fixture
def meshes():
    return [s for s in parse_gdml_bytes(B1_LIKE) if isinstance(s, PlacedMesh)]


def test_the_shapes_are_meshes(meshes):
    assert {m.solid_type for m in meshes} == {"Cons", "Trd"}


def test_each_face_carries_its_own_unit_normal(meshes):
    for mesh in meshes:
        assert len(mesh.vertex_normals) == len(mesh.local_vertices_mm)
        normals = mesh.vertex_normals.reshape(-1, 3, 3)
        np.testing.assert_allclose(np.linalg.norm(normals, axis=2), 1.0, atol=1e-5)
        np.testing.assert_array_equal(normals[:, 0], normals[:, 1])
        np.testing.assert_array_equal(normals[:, 0], normals[:, 2])


def test_normals_point_out_of_the_convex_solids(meshes):
    for mesh in meshes:
        corners = mesh.local_vertices_mm.reshape(-1, 3, 3)
        outward = corners.mean(axis=1) - mesh.local_vertices_mm.mean(axis=0)
        assert ((mesh.vertex_normals[::3] * outward).sum(axis=1) > 0.0).all()
