-- Fixture: package body with an internal call graph.
-- Exercises: enclosing-routine tracking, calls between siblings, a call to an
-- external package, a built-in that must not be recorded, and the old outer
-- join operator that looks exactly like a call.
create or replace package body pkg_inspeccion as

    function total_neto(p_numctl in number) return number is
        l_total number;
    begin
        select sum(d.netwgt)
          into l_total
          from uc_insp_det d
         where d.numctl = p_numctl;

        return l_total;
    end total_neto;

    procedure registrar_evento(p_numctl in number, p_evento in varchar2) is
    begin
        insert into uc_insp_log (numctl, evento, fecha)
        values (p_numctl, p_evento, sysdate);

        dbms_output.put_line('evento registrado');
    end registrar_evento;

    procedure cerrar_inspeccion(p_numctl in number) is
        l_peso number;
    begin
        l_peso := pkg_inspeccion.total_neto(p_numctl);

        update uc_insp_ent e
           set e.netwgt = l_peso,
               e.estado = 'CERRADO'
         where e.numctl = p_numctl;

        pkg_inspeccion.registrar_evento(p_numctl, 'CIERRE');
        pkg_auditoria.anotar(p_numctl, 'cierre de inspeccion');
    end cerrar_inspeccion;

    procedure resumen(p_numctl in number) is
    begin
        insert into uc_insp_rsm (numctl, prtnum)
        select e.numctl, p.prtnum
          from uc_insp_ent e,
               prtmst p
         where p.prtnum = e.prtnum(+)
           and e.numctl = p_numctl;
    end resumen;

end pkg_inspeccion;
/
