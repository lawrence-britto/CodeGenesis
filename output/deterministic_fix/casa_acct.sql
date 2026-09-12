SELECT
'Vietnam' AS nm_entry,
'RBC~VN~C_ACCT~CASA_ACCT~1' AS process_id,
cacct.ACCT_SROGT_ID AS s_acct,
cacct.DOM_ACCT_REF AS n_acct,
cacct.DOM_MAST_REF AS n_mast,
cacct.PRTY_SROGT_ID AS s_prty,
cacct.DOM_PRTY_REF AS n_dom_cust,
core_PID.ID_REF AS n_cust,
ptyltd.PRIM_PRTY_IND AS f_prim_prty,
core_prty.ENTRP_PRTY_SROGT_ID AS s_entrp_prty,
core_prty.ENTRP_PRTY_REF AS n_entrp_prty,
core_prty.ENTRP_PARNT_PRIM_PRTY_IND AS s_entrp_pent_prty,
core_prty.ENTRP_PARNT_PRTY_HOST_NUM AS n_entrp_pmnt_prty,
cacct.PROD_SROGT_ID AS s_prd,
cacct.DOM_PROD_CD AS c_dom_prd,
cprod.DOM_PROD_DESC AS x_prd,
cacct.ACCT_TP_CD AS c_dmcle_brnch,
cprod.PROD_CAT_DESC AS x_prdcat,
cacct.ACCT_BRNCH_SROGT_ID AS s_brnch,
cacct.ACCT_BRNCH_CD AS c_dmcle_brnch,
cacct.ACCT_STS_TP_CD AS c_acctsts,
cacct.ACCT_STS_TP_DESC AS x_acctsts,
cacct.ACCT_CURY_CD AS c_acctccy,
cabal.OS_BAL_AMT AS a_curbal_acctccy,
eacct.OBA_LCY AS a_curbal_lcy,
eacct.OBA_USD AS a_curbal_usd,
cacct.ACCT_OPEN_DT AS d_acctopn,
cacct.ACCT_CLSE_DT AS d_acctcls,
cacct.SOURCE_COUNTRY_CODE AS c_cntry,
cacct.ACCT_CLSE_RESN_CD AS c_acctclsrsn,
core_prty.SEGMT_CD AS c_glcusttyp,
core_prty.PRTY_SEGMT_CLAS AS x_glcusttyp,
core_prty.PRTY_SEGMT_ID AS id_glcusttyp,
cacct.REFL_ID AS id_refl,
cacct.SRCG_ID AS id_srcg,
cacct.CLSG_ID AS id_clsg,
cacct.SUB_SEGMT_CD AS c_custsubseg,
cacct.SUB_SEGMT_CD_DESC AS x_custsubseg,
cacct.DATA_SRC AS data_src,
cacct.SOURCE_COUNTRY_CODE AS Source_country_code,
cacct.ACCS_CTRY_CD AS accs_ctry_cd,
cacct.ACCS_SEGMT_CD AS accs_segmt_cd
FROM (SELECT ACCS_CTRY_CD, ACCS_SEGMT_CD, ACCT_BRNCH_CD, ACCT_BRNCH_SROGT_ID, ACCT_CLSE_DT, ACCT_CLSE_RESN_CD, ACCT_CURY_CD, ACCT_OPEN_DT, ACCT_SROGT_ID, ACCT_STS_TP_CD, ACCT_STS_TP_DESC, ACCT_TP_CD, CLSG_ID, DATA_SRC, DOM_ACCT_REF, DOM_MAST_REF, DOM_PROD_CD, DOM_PRTY_REF, PROD_SROGT_ID, PRTY_SROGT_ID, REFL_ID, SOURCE_COUNTRY_CODE, SRCG_ID, SUB_SEGMT_CD, SUB_SEGMT_CD_DESC, acct_srogt_id, prod_srogt_id, prty_srogt_id FROM c_acct
    WHERE DATA_SRC = 'EBB'
   AND SOURCE_COUNTRY_CODE = 'VN'
   AND process_id = 'EBB~VN~EBBS_VN_ACCOUNT~C_ACCT~1'
) cacct

LEFT JOIN (SELECT ID_REF, PRTY_SROGT_ID, prty_srogt_id FROM C_PRTY_ID
    WHERE DATA_SRC = 'EBB'
   AND SOURCE_COUNTRY_CODE = 'VN'
   AND ID_TP_CD = 'N01'
) core_PID
    ON trim(cacct.prty_srogt_id) = trim(core_PID.PRTY_SROGT_ID)
   AND core_PID.prty_srogt_id <> ''
LEFT JOIN (
    SELECT prty_srogt_id, SEGMT_CD,PRTY_SEGMT_ID,PRTY_SEGMT_CLAS, ENTRP_PRTY_SROGT_ID,ENTRP_PRTY_REF
    FROM c_prty
    WHERE DATA_SRC = 'EBB'
   AND SOURCE_COUNTRY_CODE = 'VN'
) core_prty
    ON trim(cacct.prty_srogt_id) = trim(core_prty.prty_srogt_id)
   AND core_prty.prty_srogt_id <> ''
LEFT JOIN (SELECT OS_BAL_AMT, acct_srogt_id FROM C_ACCT_BAL_MTRC
    WHERE data_src = 'EBB'
   AND source_country_code = 'VN'
) cabal
    ON cabal.acct_srogt_id = cacct.acct_srogt_id
   AND cabal.acct_srogt_id <> ''
LEFT JOIN (
    SELECT acct_srogt_id,prty_srogt_id,PRIM_PRTY_IND
    FROM C_PRTY_ACCT_RLTD
    WHERE data_src = 'EBB'
   AND source_country_code = 'VN'
   AND process_id = 'EBB~VN~EBBS_VN_ACCOUNT~C_PRTY_ACCT_RLTD~1'
) ptyltd
    ON ptyltd.acct_srogt_id = cacct.acct_srogt_id
   AND trim(ptyltd.prty_srogt_id) = trim(cacct.prty_srogt_id)

LEFT JOIN (SELECT OBA_LCY, OBA_USD, acct_srogt_id FROM E_ACCT_BASE
    WHERE data_src = 'EBB'
   AND source_country_code = 'VN'
   AND process_id = 'EBB~VN~EBBS_VN_ACCOUNT~E_ACCT_BASE~1'
) eacct
    ON eacct.acct_srogt_id = cacct.acct_srogt_id
   AND eacct.acct_srogt_id <> ''
LEFT JOIN (
    SELECT prod_srogt_id, PROD_CAT_DESC, DOM_PROD_DESC, OD_IND
    FROM C_PROD
    WHERE data_src = 'EBB'
   AND source_country_code = 'VN'
) cprod
    ON cprod.prod_srogt_id = cacct.prod_srogt_id
   AND cprod.prod_srogt_id <> '';