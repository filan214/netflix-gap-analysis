"""Build netflix_dashboard.twbx from netflix_gap_marts_plain.xlsx.

Usage: python3 build_tableau.py <marts.xlsx> <template_map.twbx> <out.twbx> [twb_out_dir]

Design rules (from the project handoff):
  high-rated = IMDb 7.0+ and 1,000+ votes; groups under 30 matched titles are never ranked;
  Indonesia is descriptive only; shares are decimals formatted as percent; accent #E50914 plus greys.

Build rules learned the hard way:
  - No dual axis. `(a + b)` on a shelf gives two stacked panes, not a merged axis.
  - A palette style-rule references the field WITHOUT the datasource prefix ([none:X:nk]),
    unlike an interpolated one, which keeps it.
  - Dashboard zones: layout-basic with exact non-overlapping tiling in a 100000-unit space.
"""
import sys, re, zipfile, os, html
import pandas as pd

XLSX, TEMPLATE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
TWB_DIR = sys.argv[4] if len(sys.argv) > 4 else None

RED, GREY, DGREY, LINEGREY = '#E50914', '#BFBFBF', '#7F7F7F', '#D6D6D6'
GITHUB = 'https://github.com/filan214/netflix-gap-analysis'
DASH = 'Netflix catalog quality'


def esc(s):
    return html.escape(str(s), quote=True)


# ----------------------------------------------------------------- data prep
sheets = pd.read_excel(XLSX, sheet_name=None)
sens = sheets['sensitivity_genre'].copy()
gap = sheets['coverage_gap_genre'].copy()
growth = sheets['growth_by_year_added'].copy()
ivg = sheets['indonesia_vs_global'].copy()
country = sheets['country_votes_context'].copy()

# short rule labels; the full definitions live in the subtitle
RULE = {1: 'Standard', 2: 'Lenient', 3: 'Strict', 4: 'Standard, clean matches'}
sens['Rule'] = sens['Scenario Number'].map(RULE)
rankable = sens[~sens['Too Few Titles to Rank'].astype(bool)]
best = rankable.groupby('Genre')['Quality Rank'].min()
top5_genres = sorted(best[best <= 5].index)
sens['Ever in Top 5'] = sens['Genre'].isin(top5_genres)
# label only at the right-hand end of each line
sens['Genre Label'] = sens.apply(lambda r: r['Genre'] if r['Scenario Number'] == 4 else '', axis=1)

gap['Compared With World'] = ['Netflix is thinner' if v >= 1.0 else 'Netflix is not thinner' for v in gap['Gap Score']]

ivg_long = pd.concat([
    ivg.assign(**{'Compared Group': 'Indonesia', 'Share of Titles': ivg['Share of Indonesian Titles'],
                  'Titles in Group': ivg['Indonesian Titles']}),
    ivg.assign(**{'Compared Group': 'All Netflix', 'Share of Titles': ivg['Share of All Netflix Titles'],
                  'Titles in Group': ivg['All Netflix Titles']}),
])
_g = ivg[ivg['Group Type'] == 'Genre']
_top = set(_g[_g['Indonesian Titles'] > 0].nlargest(10, 'Share of Indonesian Titles')['Group Name'])
ivg_long['Has Indonesian Titles'] = ivg_long['Group Name'].isin(_top)
ivg_long = ivg_long[['Group Type', 'Group Name', 'Compared Group', 'Share of Titles', 'Titles in Group',
                     'Has Indonesian Titles', 'Share of Indonesian Titles']].rename(
    columns={'Share of Indonesian Titles': 'Indonesian Share'}).reset_index(drop=True)

# ----------------------------------------------------------------- datasource plumbing
TYPES = {'string': (129, 'Count'), 'integer': (20, 'Sum'), 'real': (5, 'Sum'), 'boolean': (11, 'Count')}


def dtype_of(s):
    if s.dtype == bool:
        return 'boolean'
    if pd.api.types.is_integer_dtype(s):
        return 'integer'
    if pd.api.types.is_float_dtype(s):
        return 'real'
    return 'string'


class DS:
    def __init__(self, key, name, df, formats=None):
        self.key, self.name, self.df = key, name, df
        self.id, self.conn, self.csv = f'federated.{key}', f'textscan.{key}', f'{name}.csv'
        self.fmt = formats or {}
        self.types = {c: dtype_of(df[c]) for c in df.columns}
        self.extra_cols = ''
        self.colors = []        # (field-instance name, [(member, hex)]) -> datasource <style>

    def ref(self, inst):
        return f'[{self.id}].[{esc(inst)}]'

    def xml(self):
        cols = ''.join(f"<column datatype='{t}' name='{esc(c)}' ordinal='{i}' />"
                       for i, (c, t) in enumerate(self.types.items()))
        rel = (f"<relation connection='{self.conn}' name='{self.csv}' table='[{self.name}#csv]' type='table'>"
               f"<columns character-set='UTF-8' header='yes' locale='en_US' separator=','>{cols}</columns></relation>")
        recs = ["<metadata-record class='capability'><remote-name /><remote-type>0</remote-type>"
                f"<parent-name>[{self.csv}]</parent-name><remote-alias /><aggregation>Count</aggregation>"
                "<contains-null>true</contains-null><attributes>"
                "<attribute datatype='string' name='character-set'>&quot;UTF-8&quot;</attribute>"
                "<attribute datatype='string' name='collation'>&quot;en_US&quot;</attribute>"
                "<attribute datatype='string' name='field-delimiter'>&quot;,&quot;</attribute>"
                "<attribute datatype='string' name='header-row'>&quot;true&quot;</attribute>"
                "<attribute datatype='string' name='locale'>&quot;en_US&quot;</attribute>"
                "<attribute datatype='string' name='single-char'>&quot;&quot;</attribute>"
                "</attributes></metadata-record>"]
        for i, (c, t) in enumerate(self.types.items()):
            rt, agg = TYPES[t]
            extra = "<scale>1</scale><width>1073741823</width>" if t == 'string' else ''
            coll = "<collation flag='0' name='LEN_RUS' />" if t == 'string' else ''
            recs.append(f"<metadata-record class='column'><remote-name>{esc(c)}</remote-name>"
                        f"<remote-type>{rt}</remote-type><local-name>[{esc(c)}]</local-name>"
                        f"<parent-name>[{self.csv}]</parent-name><remote-alias>{esc(c)}</remote-alias>"
                        f"<ordinal>{i}</ordinal><local-type>{t}</local-type><aggregation>{agg}</aggregation>"
                        f"{extra}<contains-null>true</contains-null>{coll}"
                        "<object-id>[Migrated Data]</object-id></metadata-record>")
        colxml = [col_def(self, c) for c in sorted(self.types, key=str.lower)]
        colxml.append("<column caption='Migrated Data' datatype='table' "
                      "name='[__tableau_internal_object_id__].[Migrated Data]' role='measure' type='quantitative' />")
        if self.extra_cols:
            colxml.append(self.extra_cols)
        for inst, _ in self.colors:
            src = inst.split(':')[1]
            colxml.append(f"<column-instance column='[{esc(src)}]' derivation='None' name='[{esc(inst)}]' "
                          f"pivot='key' type='nominal' />")
        colxml.append("<layout dim-ordering='alphabetic' measure-ordering='alphabetic' show-structure='true' />")
        if self.colors:
            rules = ''.join(palette(inst, mapping) for inst, mapping in self.colors)
            colxml.append(f"<style>{rules}</style>")
        return (f"<datasource caption='{self.name}' inline='true' name='{self.id}' version='18.1'>"
                f"<connection class='federated'><named-connections>"
                f"<named-connection caption='{self.name}' name='{self.conn}'>"
                f"<connection class='textscan' directory='Data/Datasources' filename='{self.csv}' password='' server='' />"
                f"</named-connection></named-connections>{rel}"
                f"<metadata-records>{''.join(recs)}</metadata-records></connection><aliases enabled='yes' />"
                f"{''.join(colxml)}"
                f"<object-graph><objects><object caption='Migrated Data' id='Migrated Data'>"
                f"<properties context=''>{rel}</properties></object></objects></object-graph></datasource>")

    def dep(self, items):
        return f"<datasource-dependencies datasource='{self.id}'>{''.join(items)}</datasource-dependencies>"


def col_def(ds, name):
    t = ds.types[name]
    dim = t in ('string', 'boolean')
    f = f" default-format='{ds.fmt[name]}'" if name in ds.fmt else ''
    return (f"<column caption='{esc(name)}' datatype='{t}'{f} name='[{esc(name)}]' "
            f"role='{'dimension' if dim else 'measure'}' type='{'nominal' if dim else 'quantitative'}' />")


def ci(col, deriv, short, typ):
    """column-instance xml + its instance name."""
    sfx = {'nominal': 'nk', 'ordinal': 'ok', 'quantitative': 'qk'}[typ]
    nm = f'{short}:{col}:{sfx}'
    return (f"<column-instance column='[{esc(col)}]' derivation='{deriv}' name='[{esc(nm)}]' "
            f"pivot='key' type='{typ}' />"), nm


def calc_def(name, caption, datatype, role, typ, formula):
    return (f"<column caption='{esc(caption)}' datatype='{datatype}' name='[{name}]' role='{role}' type='{typ}'>"
            f"<calculation class='tableau' formula='{esc(formula)}' /></column>")


# palette rules drop the datasource prefix; interpolated ones keep it
def palette(inst, mapping):
    maps = ''.join(f"<map to='{c}'><bucket>&quot;{esc(k)}&quot;</bucket></map>" for k, c in mapping)
    return f"<style-rule element='mark'><encoding attr='color' field='[{esc(inst)}]' type='palette'>{maps}</encoding></style-rule>"


def bool_palette(inst, true_color, false_color):
    return (f"<style-rule element='mark'><encoding attr='color' field='[{esc(inst)}]' type='palette'>"
            f"<map to='{true_color}'><bucket>true</bucket></map>"
            f"<map to='{false_color}'><bucket>false</bucket></map></encoding></style-rule>")


def axis_title(ds, inst, scope, text):
    return (f"<style-rule element='axis'><format attr='title' class='0' field='{ds.ref(inst)}' "
            f"scope='{scope}' value='{esc(text)}' /></style-rule>")


def axis_reverse(ds, inst, scope):
    return (f"<style-rule element='axis'><encoding attr='space' class='0' field='{ds.ref(inst)}' "
            f"field-type='quantitative' reverse='true' scope='{scope}' type='space' /></style-rule>")


def cat_filter(ds, inst, members, exclude=False):
    ms = ''.join(f"<groupfilter function='member' level='[{esc(inst)}]' member='{m}' />" for m in members)
    if exclude:
        return (f"<filter class='categorical' column='{ds.ref(inst)}'>"
                f"<groupfilter function='except' user:ui-domain='database' user:ui-enumeration='exclusive' "
                f"user:ui-marker='enumerate'><groupfilter function='level-members' level='[{esc(inst)}]' />{ms}"
                f"</groupfilter></filter>")
    if len(members) == 1:
        m = members[0]
        return (f"<filter class='categorical' column='{ds.ref(inst)}'>"
                f"<groupfilter function='member' level='[{esc(inst)}]' member='{m}' "
                f"user:ui-domain='database' user:ui-enumeration='inclusive' user:ui-marker='enumerate' /></filter>")
    return (f"<filter class='categorical' column='{ds.ref(inst)}'>"
            f"<groupfilter function='union' user:ui-domain='database' user:ui-enumeration='inclusive' "
            f"user:ui-marker='enumerate'>{ms}</groupfilter></filter>")


_uid = [0]


def uid():
    _uid[0] += 1
    return '9B1E7A%02X-5C2D-4E8F-A3B1-6D4F2C8E%04X' % (_uid[0], 0x1000 + _uid[0])


def title_block(title, sub):
    return (f"<layout-options><title><formatted-text>"
            f"<run bold='true' fontsize='15'>{esc(title)}</run><run>Æ&#10;</run>"
            f"<run fontcolor='#666666' fontsize='10'>{esc(sub)}</run>"
            f"</formatted-text></title></layout-options>")


def pane(pid, mark, encodings='', style='', extra='', tooltip=''):
    # schema order inside <pane>: encodings, reference-line, customized-tooltip, style
    st = f'<style>{style}</style>' if style else ''
    enc = f'<encodings>{encodings}</encodings>' if encodings else ''
    tip = (f"<customized-tooltip show-buttons='true'><formatted-text>{tooltip}</formatted-text>"
           f"</customized-tooltip>") if tooltip else ''
    return (f"<pane id='{pid}' selection-relaxation-option='selection-relaxation-allow'>"
            f"<view><breakdown value='auto' /></view><mark class='{mark}' />{enc}{extra}{tip}{st}</pane>")


def t_head(text):
    return f"<run bold='true' fontsize='12'>{esc(text)}</run>"


def t_txt(text):
    return f"<run fontsize='11' fontcolor='#444444'>{esc(text)}</run>"


def t_fld(ds, inst):
    return f"<run bold='true' fontsize='11'>&lt;{ds.ref(inst)}&gt;</run>"


NL = "<run>\u00c6&#10;</run>"


WS = {}


def worksheet(name, title, sub, ds, deps, rows, cols, panes, filters='', sort='', slices='', style=''):
    WS[name] = uid()
    return (f"<worksheet name='{esc(name)}'>{title_block(title, sub)}<table><view>"
            f"<datasources><datasource caption='{ds.name}' name='{ds.id}' /></datasources>"
            f"{ds.dep(deps)}{filters}{sort}{slices}<aggregation value='true' /></view>"
            f"<style>{style}</style><panes>{panes}</panes><rows>{rows}</rows><cols>{cols}</cols></table>"
            f"<simple-id uuid='{{{WS[name]}}}' /></worksheet>")


# ----------------------------------------------------------------- datasources
ds_sens = DS('1netflixsens001', 'sensitivity_genre', sens, formats={'Quality Rank': 'n#,##0'})
ds_gap = DS('1netflixgap0001', 'coverage_gap_genre', gap,
            formats={'Genre Share of Netflix Highly Rated': 'p0.0%', 'Genre Share of World Highly Rated': 'p0.0%',
                     'Gap Score': 'n#,##0.00'})
ds_growth = DS('1netflixgrow001', 'growth_by_year_added', growth)
ds_ivg = DS('1netflixindo001', 'indonesia_vs_global_long', ivg_long,
            formats={'Share of Titles': 'p0.0%', 'Indonesian Share': 'p0.0%'})

CAL_HI = 'Calculation_1000000000000001'
CAL_YEAR = 'Calculation_1000000000000003'
hi_def = calc_def(CAL_HI, 'Stays in the top 5', 'string', 'dimension', 'nominal',
                  'IF [Genre] = "Classic Movies" OR [Genre] = "Anime Series" '
                  'THEN "In the top 5 every time" ELSE "Drops out under some rule" END')
yr_def = calc_def(CAL_YEAR, 'Year added', 'date', 'dimension', 'ordinal',
                  'MAKEDATE([Year Added to Netflix],1,1)')
ds_sens.extra_cols = hi_def
ds_growth.extra_cols = yr_def

# ----------------------------------------------------------------- Sheet 2: rank stability
s = ds_sens
d_rule, n_rule = ci('Rule', 'None', 'none', 'nominal')
d_scnum, n_scnum = ci('Scenario Number', 'Min', 'min', 'quantitative')
d_rank, n_rank = ci('Quality Rank', 'Avg', 'avg', 'quantitative')
d_genre, n_genre = ci('Genre', 'None', 'none', 'nominal')
d_lab, n_lab = ci('Genre Label', 'None', 'none', 'nominal')
d_few, n_few = ci('Too Few Titles to Rank', 'None', 'none', 'nominal')
d_top5, n_top5 = ci('Ever in Top 5', 'None', 'none', 'nominal')
n_hi = f'none:{CAL_HI}:nk'
d_hi = f"<column-instance column='[{CAL_HI}]' derivation='None' name='[{n_hi}]' pivot='key' type='nominal' />"
sheet2 = worksheet(
    'Rank stability', 'Change the rule and the best genres change',
    'Each line is a genre, ranked 1 = best. Only Classic Movies and Anime Series (red) stay in the top 5 '
    'under all four rules.',
    s, [col_def(s, 'Genre'), col_def(s, 'Genre Label'), col_def(s, 'Quality Rank'), col_def(s, 'Rule'),
        col_def(s, 'Scenario Number'), col_def(s, 'Too Few Titles to Rank'), col_def(s, 'Ever in Top 5'), hi_def,
        d_rule, d_scnum, d_rank, d_genre, d_lab, d_few, d_top5, d_hi],
    s.ref(n_rank), s.ref(n_rule),
    pane(1, 'Line', f"<color column='{s.ref(n_hi)}' /><lod column='{s.ref(n_genre)}' /><text column='{s.ref(n_lab)}' />",
         style="<style-rule element='mark'><format attr='mark-labels-show' value='true' />"
               "<format attr='mark-labels-cull' value='true' /></style-rule>",
         tooltip=t_head('') + t_fld(s, n_genre) + NL + t_txt('Ranks ') + t_fld(s, n_rank)
                 + t_txt(' under the ') + t_fld(s, n_rule) + t_txt(' rule.')),
    filters=cat_filter(s, n_few, ['false']) + cat_filter(s, n_top5, ['true']),
    sort=f"<sort class='computed' column='{s.ref(n_rule)}' direction='ASC' using='{s.ref(n_scnum)}' />",
    slices=f"<slices><column>{s.ref(n_few)}</column><column>{s.ref(n_top5)}</column></slices>",
    style=axis_reverse(s, n_rank, 'rows') + axis_title(s, n_rank, 'rows', 'Quality rank (1 = best)'))

# ----------------------------------------------------------------- Sheet 3: gap vs world
g = ds_gap
d_ggen, n_ggen = ci('Genre', 'None', 'none', 'nominal')
d_gs, n_gs = ci('Gap Score', 'Avg', 'avg', 'quantitative')
d_mt, n_mt = ci('Movies or TV Series', 'None', 'none', 'nominal')
d_gfew, n_gfew = ci('Too Few Titles to Rank', 'None', 'none', 'nominal')
d_thin, n_thin = ci('Compared With World', 'None', 'none', 'nominal')
d_nsh, n_nsh = ci('Genre Share of Netflix Highly Rated', 'Avg', 'avg', 'quantitative')
d_wsh, n_wsh = ci('Genre Share of World Highly Rated', 'Avg', 'avg', 'quantitative')
d_gm, n_gm = ci('Titles Matched to IMDb', 'Sum', 'sum', 'quantitative')
refline = (f"<reference-line axis-column='{g.ref(n_gs)}' value-column='{g.ref(n_gs)}' enable-instant-analytics='false' "
           f"formula='constant' id='refline0' label='Same share as the world' label-type='custom' "
           f"scope='per-table' value='1.0' z-order='1' />")
sheet3 = worksheet(
    'Netflix vs world', 'Genres where Netflix is thinner than the world',
    'Past 1.00 (red), the world has a bigger share of its good titles in that genre than Netflix does.',
    g, [col_def(g, 'Gap Score'), col_def(g, 'Genre'), col_def(g, 'Genre Share of Netflix Highly Rated'),
        col_def(g, 'Genre Share of World Highly Rated'), col_def(g, 'Movies or TV Series'),
        col_def(g, 'Compared With World'), col_def(g, 'Titles Matched to IMDb'), col_def(g, 'Too Few Titles to Rank'),
        d_ggen, d_gs, d_mt, d_gfew, d_thin, d_nsh, d_wsh, d_gm],
    g.ref(n_ggen), g.ref(n_gs),
    pane(1, 'Bar', f"<color column='{g.ref(n_thin)}' /><tooltip column='{g.ref(n_nsh)}' />"
                   f"<tooltip column='{g.ref(n_wsh)}' /><tooltip column='{g.ref(n_gm)}' />",
         extra=refline,
         tooltip=t_fld(g, n_ggen) + NL + t_txt('Gap score ') + t_fld(g, n_gs) + NL
                 + t_txt('Netflix keeps ') + t_fld(g, n_nsh) + t_txt(' of its good titles here; the world ')
                 + t_fld(g, n_wsh) + t_txt('.') + NL + t_txt('From ') + t_fld(g, n_gm)
                 + t_txt(' titles matched to IMDb.')),
    filters=cat_filter(g, n_mt, ['&quot;Movie&quot;']) + cat_filter(g, n_gfew, ['false']),
    sort=f"<sort class='computed' column='{g.ref(n_ggen)}' direction='DESC' using='{g.ref(n_gs)}' />",
    slices=f"<slices><column>{g.ref(n_mt)}</column><column>{g.ref(n_gfew)}</column></slices>",
    style=axis_title(g, n_gs, 'cols', 'Gap score (world share / Netflix share)'))

# ----------------------------------------------------------------- Sheet 4: catalog growth
w = ds_growth
n_yr = f'tyr:{CAL_YEAR}:qk'
d_yr = f"<column-instance column='[{CAL_YEAR}]' derivation='Year-Trunc' name='[{n_yr}]' pivot='key' type='quantitative' />"
n_gyr = f'yr:{CAL_YEAR}:ok'
d_gyr = f"<column-instance column='[{CAL_YEAR}]' derivation='Year' name='[{n_gyr}]' pivot='key' type='ordinal' />"
d_tot, n_tot = ci('Total Titles Added', 'Sum', 'sum', 'quantitative')
d_kind, n_kind = ci('Movie or TV Show', 'None', 'none', 'nominal')
sheet4 = worksheet(
    'Catalog growth', 'Most of the catalog arrived after 2016',
    'Titles added each year. Red = movies, grey = TV shows.',
    w, [yr_def, col_def(w, 'Movie or TV Show'), col_def(w, 'Total Titles Added'),
        col_def(w, 'Year Added to Netflix'), d_yr, d_gyr, d_tot, d_kind],
    w.ref(n_tot), w.ref(n_yr),
    pane(1, 'Area', f"<color column='{w.ref(n_kind)}' />",
         tooltip=t_fld(w, n_gyr) + NL + t_fld(w, n_tot) + t_txt(' titles added (')
                 + t_fld(w, n_kind) + t_txt(').')),
    style=axis_title(w, n_tot, 'rows', 'Titles added') + axis_title(w, n_yr, 'cols', 'Year added to Netflix'))

# ----------------------------------------------------------------- Sheet 5: Indonesia growth
n_yr2 = f'yr:{CAL_YEAR}:ok'
d_yr2 = f"<column-instance column='[{CAL_YEAR}]' derivation='Year' name='[{n_yr2}]' pivot='key' type='ordinal' />"
d_ind, n_ind = ci('Indonesian Titles Added', 'Sum', 'sum', 'quantitative')
sheet5 = worksheet(
    'Indonesia growth', 'Indonesian titles added each year',
    '90 in total. Counts only — too few titles to score or rank.',
    w, [yr_def, col_def(w, 'Indonesian Titles Added'), col_def(w, 'Year Added to Netflix'), d_yr2, d_ind],
    w.ref(n_ind), w.ref(n_yr2),
    pane(1, 'Bar', f"<text column='{w.ref(n_ind)}' />",
         style=f"<style-rule element='mark'><format attr='mark-color' value='{RED}' />"
               f"<format attr='mark-labels-show' value='true' /></style-rule>",
         tooltip=t_fld(w, n_yr2) + NL + t_fld(w, n_ind) + t_txt(' Indonesian titles added.')),
    style=axis_title(w, n_ind, 'rows', 'Titles added') + axis_title(w, n_yr2, 'cols', 'Year added to Netflix'))

# ----------------------------------------------------------------- Sheet 6: Indonesia vs all Netflix
v = ds_ivg
d_gn, n_gn = ci('Group Name', 'None', 'none', 'nominal')
d_gt, n_gt = ci('Group Type', 'None', 'none', 'nominal')
d_cg, n_cg = ci('Compared Group', 'None', 'none', 'nominal')
d_sh, n_sh = ci('Share of Titles', 'Avg', 'avg', 'quantitative')
d_isort, n_isort = ci('Indonesian Share', 'Avg', 'avg', 'quantitative')
d_has, n_has = ci('Has Indonesian Titles', 'None', 'none', 'nominal')
sheet6 = worksheet(
    'Indonesia vs all Netflix', 'Indonesian titles next to the whole catalog',
    'The 10 genres most common among Indonesian titles. Red = Indonesian (79 titles), '
    'grey = all Netflix (7,492).',
    v, [col_def(v, 'Compared Group'), col_def(v, 'Group Name'), col_def(v, 'Group Type'),
        col_def(v, 'Has Indonesian Titles'), col_def(v, 'Indonesian Share'), col_def(v, 'Share of Titles'),
        d_gn, d_gt, d_cg, d_sh, d_isort, d_has],
    f"{v.ref(n_gn)} / {v.ref(n_cg)}", v.ref(n_sh),
    pane(1, 'Bar', f"<color column='{v.ref(n_cg)}' />",
         tooltip=t_fld(v, n_gn) + NL + t_fld(v, n_cg) + t_txt(': ') + t_fld(v, n_sh)
                 + t_txt(' of titles.')),
    filters=cat_filter(v, n_gt, ['&quot;Genre&quot;']) + cat_filter(v, n_has, ['true']),
    sort=f"<sort class='computed' column='{v.ref(n_gn)}' direction='DESC' using='{v.ref(n_isort)}' />",
    slices=f"<slices><column>{v.ref(n_gt)}</column><column>{v.ref(n_has)}</column></slices>",
    style=axis_title(v, n_sh, 'cols', 'Share of titles in the genre'))

ds_sens.colors = [(n_hi, [('In the top 5 every time', RED), ('Drops out under some rule', GREY)])]
ds_gap.colors = [(n_thin, [('Netflix is thinner', RED), ('Netflix is not thinner', GREY)])]
ds_growth.colors = [(n_kind, [('Movie', RED), ('TV Show', DGREY)])]
ds_ivg.colors = [(n_cg, [('Indonesia', RED), ('All Netflix', DGREY)])]

# ----------------------------------------------------------------- dashboard (1400 x 2000, exact tiling)
_z = [100]


def z():
    _z[0] += 1
    return _z[0]


CARD = ("<zone-style><format attr='border-color' value='#E0E0E0' />"
        "<format attr='border-style' value='solid' /><format attr='border-width' value='1' />"
        "<format attr='background-color' value='#ffffff' /></zone-style>")


def vis(name, x, y, w_, h):
    return f"<zone h='{h}' id='{z()}' name='{esc(name)}' w='{w_}' x='{x}' y='{y}'>{CARD}</zone>"


def textzone(x, y, w_, h, runs):
    return f"<zone h='{h}' id='{z()}' type-v2='text' w='{w_}' x='{x}' y='{y}'><formatted-text>{runs}</formatted-text></zone>"


zones = (
    textzone(0, 0, 100000, 4500,
             "<run bold='true' fontsize='24'>What one rating rule hides in Netflix's catalog</run>")
    + vis('Map', 0, 4500, 50000, 25000)
    + vis('Indonesia vs all Netflix', 50000, 4500, 50000, 25000)
    + vis('Rank stability', 0, 29500, 100000, 22500)
    + vis('Netflix vs world', 0, 52000, 82000, 26000)
    + f"<zone h='26000' id='{z()}' mode='checkdropdown' name='Netflix vs world' param='{g.ref(n_mt)}' "
      f"type-v2='filter' w='18000' x='82000' y='52000' />"
    + vis('Catalog growth', 0, 78000, 50000, 18500)
    + vis('Indonesia growth', 50000, 78000, 50000, 18500)
    + textzone(0, 96500, 100000, 3500,
               "<run fontcolor='#666666' fontsize='10'>Netflix titles (Kaggle, 2021) matched to IMDb ratings. "
               "Good = rated 7.0+ with 1,000+ votes. Method and limits: </run>"
               f"<run fontcolor='#666666' fontsize='10' hyperlink='{esc(GITHUB)}'>{esc(GITHUB)}</run>"))

# ----------------------------------------------------------------- assemble
tpl = zipfile.ZipFile(TEMPLATE).read('netflix_map.twb').decode('utf-8')
head = tpl[:tpl.index('<datasources>')]
ds_country = re.search(
    r"(<datasource caption='country_votes_context' inline='true'.*?</datasource>)", tpl, re.S).group(1)
CID = re.search(r"name='(federated\.[^']+)' version", ds_country).group(1)
map_ws = re.search(r"<worksheet name='Map'>.*?</worksheet>", tpl, re.S).group(0)
map_uuid = re.search(r"<simple-id uuid='\{([^}]+)\}' />\s*</worksheet>", map_ws).group(1)
# shorter subtitle so the pane is not swallowed by text
map_ws = re.sub(r"(<run fontcolor='#666666' fontsize='10'>)[^<]*(</run>)",
                r"\1Titles rated 7+ but with under 1,000 votes. Darker = more. Average: 9.4%.\2", map_ws)
map_ws = re.sub(r"(<run bold='true' fontsize='14'>)[^<]*(</run>)",
                r"\1Good titles that too few people rated\2", map_ws)
MAP_TIP = ("<customized-tooltip show-buttons='true'><formatted-text>"
           f"<run bold='true' fontsize='11'>&lt;[{CID}].[none:Country:nk]&gt;</run>"
           "<run fontsize='11'>\n</run>"
           f"<run bold='true' fontsize='11'>&lt;[{CID}].[sum:Share Hidden by Low Votes:qk]&gt;</run>"
           "<run fontsize='11' fontcolor='#444444'> of its titles are rated 7+ but have under 1,000 votes.</run>"
           "<run fontsize='11'>\n</run>"
           f"<run bold='true' fontsize='11'>&lt;[{CID}].[sum:Share Rated 7 or Higher:qk]&gt;</run>"
           "<run fontsize='11' fontcolor='#444444'> are rated 7+ overall, out of </run>"
           f"<run bold='true' fontsize='11'>&lt;[{CID}].[sum:Titles Matched to IMDb:qk]&gt;</run>"
           "<run fontsize='11' fontcolor='#444444'> titles matched to IMDb.</run>"
           "</formatted-text></customized-tooltip>")
map_ws = map_ws.replace('</encodings>', '</encodings>' + MAP_TIP, 1)
map_ws = map_ws.replace("palette='red_10_0' type='interpolated'",
                        "num-steps='5' palette='red_10_0' type='interpolated'")

all_ds = [('country_votes_context', CID)] + [(d.name, d.id) for d in (ds_sens, ds_gap, ds_growth, ds_ivg)]
dashboard = (
    f"<dashboard name='{DASH}'><style />"
    f"<size maxheight='2000' maxwidth='1400' minheight='2000' minwidth='1400' sizing-mode='fixed' />"
    f"<datasources>" + ''.join(f"<datasource caption='{c}' name='{i}' />" for c, i in all_ds) + "</datasources>"
    f"<zones><zone h='100000' id='{z()}' type-v2='layout-basic' w='100000' x='0' y='0'>{zones}</zone></zones>"
    f"<simple-id uuid='{{{uid()}}}' /></dashboard>")

ON_DASH = ['Map', 'Indonesia vs all Netflix', 'Rank stability', 'Netflix vs world',
           'Catalog growth', 'Indonesia growth']
ALL_SHEETS = list(ON_DASH)


def window(name, wuid):
    return (f"<window class='worksheet' name='{esc(name)}'><cards>"
            f"<edge name='left'><strip size='160'><card type='pages' /><card type='filters' /><card type='marks' /></strip></edge>"
            f"<edge name='top'><strip size='2147483647'><card type='columns' /></strip>"
            f"<strip size='2147483647'><card type='rows' /></strip><strip size='31'><card type='title' /></strip></edge>"
            f"</cards><simple-id uuid='{{{wuid}}}' /></window>")


windows = [window('Map', map_uuid)] + [window(n, WS[n]) for n in ALL_SHEETS if n != 'Map']
windows.append(f"<window class='dashboard' maximized='true' name='{esc(DASH)}'><viewpoints>"
               + ''.join(f"<viewpoint name='{esc(n)}'><zoom type='entire-view' /></viewpoint>" for n in ON_DASH)
               + f"</viewpoints><active id='-1' /><simple-id uuid='{{{uid()}}}' /></window>")

ACTIONS = ("<actions><action caption='Show that year in the Indonesia chart' name='[Action1]'>"
           "<activation auto-clear='true' type='on-select' />"
           f"<source dashboard='{esc(DASH)}' type='sheet' worksheet='Catalog growth' />"
           "<command command='tsc:tsl-filter'>"
           "<param name='field-captions' value='Year added' />"
           f"<param name='target' value='{esc(DASH)}' />"
           "</command></action></actions>")

body = (head + '<datasources>' + ds_country + ''.join(d.xml() for d in (ds_sens, ds_gap, ds_growth, ds_ivg))
        + '</datasources>'
        + "<mapsources><mapsource name='Tableau' /></mapsources>" + ACTIONS
        + '<worksheets>' + map_ws + sheet2 + sheet3 + sheet4 + sheet5 + sheet6 + '</worksheets>'
        + '<dashboards>' + dashboard + '</dashboards>'
        + "<windows source-height='44'>" + ''.join(windows) + '</windows></workbook>\n')

if TWB_DIR:
    os.makedirs(TWB_DIR, exist_ok=True)
    open(os.path.join(TWB_DIR, 'netflix_dashboard.twb'), 'w', encoding='utf-8').write(body)

with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED) as zo:
    zo.writestr('netflix_dashboard.twb', body.encode('utf-8'))
    for name, df in [('country_votes_context', country), ('sensitivity_genre', sens), ('coverage_gap_genre', gap),
                     ('growth_by_year_added', growth), ('indonesia_vs_global_long', ivg_long)]:
        zo.writestr(f'Data/Datasources/{name}.csv', df.to_csv(index=False, lineterminator='\n').encode('utf-8'))

print('built', OUT)
print('top-5-ever genres:', len(top5_genres), top5_genres)
print('growth total', growth['Total Titles Added'].sum(), '| indo total', growth['Indonesian Titles Added'].sum())
print('movie gap top:', gap[(gap['Movies or TV Series'] == 'Movie') & (~gap['Too Few Titles to Rank'])]
      .nlargest(1, 'Gap Score')[['Genre', 'Gap Score']].to_dict('records'))
