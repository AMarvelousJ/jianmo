"""Swept cutting-tooth boxes from the current model, not a full-circle stock debit.

XZ quadrature and <=1 degree/0.125m pose samples approximate the swept union.
Each vertical ray intersects rotated tooth boxes analytically; intervals are
merged so overlapping teeth/time samples cannot remove the same coal twice.
Coal above a removed interval settles in its column (heightfield has no voids).
"""
import math
import numpy as np


def swept_contacts(material, geometry, scene, before, after, phase_start, phase_end):
    c = geometry.config["cutting"]
    subdivisions = c["cell_quadrature"]
    previous = geometry.wheel_envelope(scene, **before)["center"]
    current = geometry.wheel_envelope(scene, **after)["center"]
    distance = math.dist(tuple(previous.values()), tuple(current.values()))
    angular = max(abs(after[a]-before[a]) for a in ("slew", "luff"))
    samples = max(1, math.ceil((abs(phase_end-phase_start)+angular)/c["max_angle_step_deg"]),
                  math.ceil(distance/c["max_translation_step_m"]))
    if samples > 1024:
        raise ValueError("Cutting step too large; split the simulation step")
    radius = geometry.swept_radius + max(abs(geometry.axial_min),abs(geometry.axial_max))
    x0 = min(previous["x"],current["x"])-radius
    z0 = min(previous["z"],current["z"])-radius
    x1 = max(previous["x"],current["x"])+radius
    z1 = max(previous["z"],current["z"])+radius
    i0=max(0,math.floor((x0-material.origin_x)/material.cell))
    i1=min(material.nx,math.ceil((x1-material.origin_x)/material.cell))
    j0=max(0,math.floor((z0-material.origin_z)/material.cell))
    j1=min(material.nz,math.ceil((z1-material.origin_z)/material.cell))
    indices=[]; px=[]; pz=[]
    for j in range(j0,j1):
        for i in range(i0,i1):
            index=j*material.nx+i
            if not material.zone_code[index] or material.heights[index]<=0: continue
            for dz in range(subdivisions):
                for dx in range(subdivisions):
                    indices.append(index)
                    px.append(material.origin_x+(i+(dx+.5)/subdivisions)*material.cell)
                    pz.append(material.origin_z+(j+(dz+.5)/subdivisions)*material.cell)
    if not indices: return {}
    px,pz=np.array(px),np.array(pz)
    ground=np.array([material.ground[i] for i in indices])
    surface=ground+np.array([material.heights[i] for i in indices])
    intervals=[[] for _ in indices]
    scale=geometry.scale
    hx,hy,hz=[v*scale*.5 for v in c["tooth_size_model"]]
    for step in range(samples+1):
        t=step/samples
        pose={a:before[a]+(after[a]-before[a])*t for a in before}
        theta=math.radians(scene["yaw"]-pose["slew"])
        center=geometry.wheel_envelope(scene,**pose)["center"]
        q=(px-center["x"])*math.cos(theta)-(pz-center["z"])*math.sin(theta)
        axial=(px-center["x"])*math.sin(theta)+(pz-center["z"])*math.cos(theta)
        axial_mask=np.abs(axial-c["tooth_axial_center_model"]*scale)<=hz
        phase=phase_start+(phase_end-phase_start)*t
        for bucket in range(c["bucket_count"]):
            angle=math.radians(bucket*360/c["bucket_count"]+phase+pose["luff"])
            phi=angle-math.pi/2
            cos,sin=math.cos(phi),math.sin(phi)
            for tooth_x in c["tooth_x_centers_model"]:
                # bucket centre is radial; teeth retain their model-local box rotation.
                u=scale*(c["bucket_radius_model"]*math.cos(angle)+tooth_x*cos-c["tooth_y_model"]*sin)
                v=scale*(c["bucket_radius_model"]*math.sin(angle)+tooth_x*sin+c["tooth_y_model"]*cos)
                low=ground.copy(); high=surface.copy(); mask=axial_mask.copy()
                for coeff,constant,half in ((sin,cos*(q-u)-sin*(center["y"]+v),hx),
                                            (cos,-sin*(q-u)-cos*(center["y"]+v),hy)):
                    if abs(coeff)<1e-12:
                        mask &= np.abs(constant)<=half
                    else:
                        a=(-half-constant)/coeff; b=(half-constant)/coeff
                        low=np.maximum(low,np.minimum(a,b)); high=np.minimum(high,np.maximum(a,b))
                for k in np.flatnonzero(mask & (high>low)):
                    intervals[k].append((float(low[k]),float(high[k])))
    contacts={}
    for index, spans in zip(indices,intervals):
        if not spans: continue
        spans.sort(); lo,hi=spans[0]; length=0.
        for a,b in spans[1:]:
            if a>hi: length+=hi-lo;lo,hi=a,b
            else: hi=max(hi,b)
        length+=hi-lo
        contacts[index]=contacts.get(index,0)+length*material.cell_area/subdivisions**2
    return contacts
