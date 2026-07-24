-- Fixture: read-only report query.
-- Exercises: JOIN, alias-qualified columns, CTE, subquery, bind variable.
with recientes as (
    select e.numctl,
           e.prtnum,
           e.netwgt,
           e.fecha_registro
      from uc_insp_ent e
     where e.fecha_registro >= sysdate - 30
)
select r.numctl,
       r.prtnum,
       p.prtdsc      as descripcion,
       r.netwgt,
       d.muestra_size_ver
  from recientes r
  join prtmst p
    on p.prtnum = r.prtnum
  left join uc_insp_det d
    on d.numctl = r.numctl
 where r.prtnum = :P117_PRTNUM
   and exists (select 1
                 from uc_insp_est s
                where s.numctl = r.numctl
                  and s.estado = 'REGISTRADO')
 order by r.fecha_registro desc;
