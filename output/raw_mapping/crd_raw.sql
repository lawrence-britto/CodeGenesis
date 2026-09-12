SELECT
ccard.CARD_SROGT_ID AS s_crd,
ccard.CARD_ACCT_SROGT_ID AS s_acct,
ccard.PRTY_SROGT_ID AS s_prty,
ccard.PROD_SROGT_ID AS s_prd,
ccard.DOM_CARD_REF AS n_dom_crd,
ccard.DOM_ACCT_REF AS n_dom_acct,
ccard.DOM_PROD_CD AS n_dom_prd,
ccard.DOM_PRTY_REF AS n_dom_cust,
ccard.DEVC_TP_CD AS c_devctp,
ccard.DEVC_TP_DESC AS x_devctp,
ccard.DATA_SRC AS data_src,
ccard.ACCS_CTRY_CD AS accs_ctry_cd,
ccard.ACCS_SEGMT_CD AS accs_segmt_cd,
ccard.SOURCE_COUNTRY_CODE AS c_untry,
ccard.CARD_BLK_CD AS C_BLK,
ccard.SOURCE_COUNTRY_CODE AS c_cntry,
ccard.CARD_BLK_CD_DESC AS X_BLK,
ccard.CARD_SEQ_NUM AS N_CRD_SEQ,
core_PID.ID_REF AS n_cust,
core_prty.SEGMT_CD AS c_glcusttyp,
core_prty.ENTRP_PRTY_SROGT_ID AS S_ENTRP_PRTY,
core_prty.ENTRP_PRTY_REF AS N_ENTRP_PRTY,
TRIM(core_prty.PRTY_SEGMT_CLAS) AS x_glcusttyp,
TRIM(core_prty.PRTY_SEGMT_CD) AS id_glcusttyp,
NULL /* TODO: confirm approved DPR rule */ AS process_id
FROM c_card ccard
left join (select PRTY_SROGT_ID, ID_REF
FROM C_PRTY_ID where DATA_SRC = 'EBB' and SOURCE_COUNTRY_CODE = 'VN' and ID_TP_CD = 'N01') core_PID
on trim(ccard.prty_srogt_id) = trim(core_PID.PRTY_SROGT_ID) and core_PID.prty_srogt_id <> "
left join (select prty_srogt_id, SEGMT_CD,PRTY_SEGMT_ID,PRTY_SEGMT_CLAS, ENTRP_PRTY_SROGT_ID,ENTRP_PRTY_REF
FROM c_prty where data_src = 'EBB' and SOURCE_COUNTRY_CODE = 'VN') core_prty
on trim(ccard.prty_srogt_id) = trim(core_prty.prty_srogt_id) and core_prty.prty_srogt_id <> ''
