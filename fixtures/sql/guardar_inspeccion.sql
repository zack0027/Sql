-- Fixture: APEX page process that writes an inspection header.
-- Exercises: INSERT, bind variables, page inference (P117_*), qualified columns.
declare
    l_numctl  uc_insp_ent.numctl%type;
    l_usuario varchar2(30) := :APP_USER;
begin
    select seq_uc_insp_ent.nextval
      into l_numctl
      from dual;

    insert into uc_insp_ent (
        numctl,
        prtnum,
        muestra_size_ver,
        netwgt,
        usuario,
        fecha_registro
    ) values (
        l_numctl,
        :P117_PRTNUM,
        :P117_MUESTRA_SIZE_VER,
        :P117_NETWGT,
        l_usuario,
        sysdate
    );

    update uc_insp_ent e
       set e.estado = 'REGISTRADO'
     where e.numctl = l_numctl;

    pkg_inspeccion.registrar_evento(p_numctl => l_numctl, p_evento => 'ALTA');
end;
/
