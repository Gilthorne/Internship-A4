<?php
$url = "http://hivecore.famnit.upr.si:6666/api/chat";

$data = [
//    "model" => "hf.co/unsloth/Qwen3-4b-Instruct-2507-GGUF:UD-Q4_K_XL",
"model" => 'hf.co/unsloth/Qwen3-4B-Thinking-2507-GGUF:UD-Q4_K_XL',
    "stream" => false,
    "keep_alive" => "5m",
    "messages" => [
        [
            "role" => "system",
            "content" => "be usefull"
        ],
        [
            "role" => "user",
            "content" => "Here is the Data Availability Part
            This work is partly based on data elaborated by the SeBAS project of the Biodiversity Exploratories program (DFG Priority Program 1374). The datasets from the German sites are publicly available in the Biodiversity Exploratories Information System BExIS (Männer, 2022).
The full spectral and laboratory data, including the data from BExIS and the used codes were published in the Mendeley Data Repository (Männer et al., 2025).

And here is the Reference part

References
Amputu, V., Knox, N., Braun, A., Heshmati, S., Retzlaff, R., R¨oder, A., Tielb¨orger, K., 2023. Unmanned aerial systems accurately map rangeland condition indicators in a dryland savannah. Eco. Inform. 75, 102007. https://doi.org/10.1016/j. ecoinf.2023.102007.
Amputu, V., M¨anner, F.A., Tielb¨orger, K., Knox, N., 2024. Spatio-temporal transferability of drone-based models to predict forage supply in drier rangelands. Remote Sens 16, 1842. https://doi.org/10.3390/rs16111842.
Asner, G.P., Heidebrecht, K.B., 2002. Spectral unmixing of vegetation, soil and dry carbon cover in arid regions: comparing multispectral and hyperspectral observations. Int. J. Remote Sens. 23, 3939–3958. https://doi.org/10.1080/ 01431160110115960.
Atlas of Namibia Team, 2022. Atlas of Namibia: Its Land, Water and Life. Namibia Nature Foundation, Windhoek.
Bazzo, C.O.G., Kamali, B., Hütt, C., Bareth, G., Gaiser, T., 2023. A review of estimation methods for aboveground biomass in grasslands using UAV. Remote Sens 15, 639. https://doi.org/10.3390/rs15030639.
Bengtsson, J., Bullock, J.M., Egoh, B., Everson, C., Everson, T., O’Connor, T., O’Farrell, P. J., Smith, H.G., Lindborg, R., 2019. Grasslands — more important for ecosystem services than you might think. Ecosphere 10, e02582. https://doi.org/10.1002/ ecs2.2582.
Bera, S., Shrivastava V., K., Chandra Satapathy, S., 2022. Advances in hyperspectral image classification based on convolutional neural networks: a review. Comput. Model. Eng. Sci. 133, 219–250. https://doi.org/10.32604/cmes.2022.020601.
BExIS, 2019. Open climate data of the Exploratories project: BExIS dataset ID 24766. In: Biodiversity Exploratories. https://www.bexis.uni-jena.de/tcd/PublicClimateData/ Index(accessed 18 January 2025).
Biewer, S., Fricke, T., Wachendorf, M., 2009. Development of canopy reflectance models to predict forage quality of legume-grass mixtures. Crop Sci. 49, 1917–1926. https:// doi.org/10.2135/cropsci2008.11.0653.
Blaix, C., Chabrerie, O., Alard, D., Catterou, M., Diquelou, S., Dutoit, T., Lacoux, J., Loucougaray, G., Michelot-Antalik, A., Pac´e, M., Tardif, A., Lemauviel-Lavenant, S., Bonis, A., 2023. Forage nutritive value shows synergies with plant diversity in a wide range of semi-natural grassland habitats. Agric. Ecosyst. Environ. 347, 108369. https://doi.org/10.1016/j.agee.2023.108369.
Blüthgen, N., Dormann, C.F., Prati, D., Klaus, V.H., Kleinebecker, T., H¨olzel, N., Alt, F., Boch, S., Gockel, S., Hemp, A., Müller, J., Nieschulze, J., Renner, S.C., Sch¨oning, I., Schumacher, U., Socher, S.A., Wells, K., Birkhofer, K., Buscot, F., Oelmann, Y., Rothenw¨ohrer, C., Scherber, C., Tscharntke, T., Weiner, C.N., Fischer, M., Kalko, E.K. V., Linsenmair, K.E., Schulze, E.-D., Weisser, W.W., 2012. A quantitative index of land-use intensity in grasslands: integrating mowing, grazing and fertilization. Basic Appl. Ecol. 13, 207–220. https://doi.org/10.1016/j.baae.2012.04.001.
Boffa, J.-M., 1999. Agroforestry Parklands in Sub-Saharan Africa. Food and Agriculture Organization of the United Nations, Rome, 230 pp.
Braham, N.A.A., Albrecht, C.M., Mairal, J., Chanussot, J., Wang, Y., Zhu, X.X., 2025. SpectralEarth: training hyperspectral foundation models at scale. IEEE J. Sel. Top. Appl. Earth Observ. Remote Sens. 18, 16780–16797. https://doi.org/10.1109/ JSTARS.2025.3581451.
Brinkmann, K., Schwieger, D.M., Grieger, L., Heshmati, S., Rauchecker, M., 2023. How and why do rangeland changes and their underlying drivers differ across Namibia’s two major land tenure systems? Rangel. J. 5 (3), 123–139.
Callo-Concha, D., Gaiser, T., Webber, H., Tischbein, B., Ewert, F., 2013. Farming in the west African Sudan savanna: insights in the context of climate change. Afr. J. Agric. Res. 8, 4693–4705.
Chen, J.M., Rich, P.M., Gower, S.T., Norman, J.M., Plummer, S., 1997. Leaf area index of boreal forests: theory, techniques, and measurements. J. Geophys. Res. 102, 29429–29443. https://doi.org/10.1029/97JD01107.
Cook, R.D., Forzani, L., 2021. PLS regression algorithms in the presence of nonlinearity. Chemom. Intell. Lab. Syst. 213, 104307. https://doi.org/10.1016/j. chemolab.2021.104307.
Cunliffe, A.M., Brazier, R.E., Anderson, K., 2016. Ultra-fine grain landscape-scale quantification of dryland vegetation structure with drone-acquired structure-from- motion photogrammetry. Remote Sens. Environ. 183, 129–143. https://doi.org/ 10.1016/j.rse.2016.05.019.
Curran, P.J., 1989. Remote sensing of foliar chemistry. Remote Sens. Environ. 30, 271–278. https://doi.org/10.1016/0034-4257(89)90069-2.
Cushnahan, T.A., Grafton, M.C.E., Pearson, D., Ramilan, T., 2024. Hyperspectral data can differentiate species and cultivars of C3 and C4 turf despite measurable diurnal variation. Remote Sens 16. https://doi.org/10.3390/rs16173142.
Da Silveira Pontes, L., Maire, V., Schellberg, J., Louault, F., 2015. Grass strategies and grassland community responses to environmental drivers: a review. Agron. Sustain. Dev. 35, 1297–1318. https://doi.org/10.1007/s13593-015-0314-1.
Dehghan-Shoar, M.H., Kereszturi, G., Pullanagari, R.R., Orsi, A.A., Yule, I.J., Hanly, J., 2024. A physically informed multi-scale deep neural network for estimating foliar nitrogen concentration in vegetation. Int. J. Appl. Earth Obs. Geoinf. 130, 103917. https://doi.org/10.1016/j.jag.2024.103917.
Delegido, J., Verrelst, J., Alonso, L., Moreno, J., 2011. Evaluation of Sentinel-2 red-edge bands for empirical estimation of green LAI and chlorophyll content. Sensors (Basel, Switzerland) 11, 7063–7081. https://doi.org/10.3390/s110707063.
Díaz, S., Lavorel, S., McIntyre, S., Falczuk, V., Casanoves, F., Milchunas, D.G., Skarpe, C., Rusch, G., Sternberg, M., Noy-Meir, I., Landsberg, J., Zhang, L., Clark, A., Campbell, B.M., 2007. Plant trait responses to grazing - a global synthesis. Glob. Chang. Biol. 13, 313–341. https://doi.org/10.1111/j.1365-2486.2006.01288.x.
Díaz, S., Kattge, J., Cornelissen, J.H.C., Wright, I.J., Lavorel, S., Dray, S., Reu, B., Kleyer, M., Wirth, C., Colin Prentice, I., Garnier, E., B¨onisch, G., Westoby, M., Poorter, H., Reich, P.B., Moles, A.T., Dickie, J., Gillison, A.N., Zanne, A.E., Chave, J., Joseph Wright, S., Sheremet’ev, S.N., Jactel, H., Baraloto, C., Cerabolini, B., Pierce, S., Shipley, B., Kirkup, D., Casanoves, F., Joswig, J.S., Günther, A., Falczuk, V., Rüger, N., Mahecha, M.D., Gorn´e, L.D., 2016. The global spectrum of plant form and function. Nature 529, 167–171. https://doi.org/10.1038/ nature16489.
Dieste, ´A.G., Argüello, F., Heras, D.B., Magdon, P., Linst¨adter, A., Dubovyk, O., Muro, J., 2024. ResNeTS: a ResNet for time series analysis of Sentinel-2 data applied to grassland plant-biodiversity prediction. IEEE J. Sel. Top. Appl. Earth Observ. Remote Sens. 17, 17349–17370. https://doi.org/10.1109/JSTARS.2024.3454271.
Duranovich, F.N., Yule, I.J., Lopez-Villalobos, N., Shadbolt, N.M., Draganova, I., Morris, S.T., 2020. Using proximal hyperspectral sensing to predict herbage nutritive value for dairy farming. Agronomy 10, 1826. https://doi.org/10.3390/ agronomy10111826.
Evans, J.S., Murphy, M.A., Holden, Z.A., Cushman, S.A., 2011. Modeling species distribution and change using random forest. In: Drew, C.A., Wiersma, Y.F., Huettmann, F. (Eds.), PREDICTIVE Species and Habitat Modeling in Landscape Ecology: Concepts and Applications. Springer Science & Business Media, New York, Dordrecht, Heidelberg [etc.], pp. 139–159.
FAO, 1989. Soil Map of the World. Wageningen, pp. 1–138.
F´eret, J.-B., Berger, K., de, Boissieu, F., Malenovský, Z., 2021. PROSPECT-PRO for estimating content of nitrogen-containing leaf proteins and other carbon-based constituents. Remote Sens. Environ. 252, 112173. https://doi.org/10.1016/j. rse.2020.112173.
Fern´andez-Habas, J., Carriere Ca˜nada, M., García Moreno, A.M., Leal-Murillo, J.R., Gonz´alez-Dugo, M.P., Abellanas Oar, B., G´omez-Gir´aldez, P.J., Fern´andez- Rebollo, P., 2022. Estimating pasture quality of Mediterranean grasslands using hyperspectral narrow bands from field spectroscopy by random Forest and PLS regressions. Comput. Electron. Agric. 192, 106614. https://doi.org/10.1016/j. compag.2021.106614.
Ferner, J., Linst¨adter, A., Südekum, K.-H., Schmidtlein, S., 2015. Spectral indicators of forage quality in West Africa’s tropical savannas. Int. J. Appl. Earth Obs. Geoinf. 41, 99–106. https://doi.org/10.1016/j.jag.2015.04.019.
Ferner, J., Schmidtlein, S., Guuroh, R.T., Lopatin, J., Linst¨adter, A., 2018. Disentangling effects of climate and land-use change on west African drylands’ forage supply. Glob. Environ. Chang. 53, 24–38. https://doi.org/10.1016/j.gloenvcha.2018.08.007.
Ferner, J., Linst¨adter, A., Rogass, C., Südekum, K.-H., Schmidtlein, S., 2021. Towards forage resource monitoring in subtropical savanna grasslands: going multispectral or hyperspectral? Eur. J. Remote Sens. 54, 364–384. https://doi.org/10.1080/ 22797254.2021.1934556.
Fick, S.E., Hijmans, R.J., 2017. WorldClim 2: new 1-km spatial resolution climate surfaces for global land areas. Int. J. Climatol. 37, 4302–4315. https://doi.org/ 10.1002/joc.5086.
Finch, H., Samuel, A.M., Lane, G., 2002. 19 - Grazing. In: Finch, H., Samuel, A.M., Lane, G. (Eds.), Lockhart and Wiseman’s Crop Husbandry Including Grassland (Eighth Edition) : Woodhead Publishing Series in Food Science, Technology and Nutrition. Woodhead Publishing, pp. 435–447.
Fischer, M., Bossdorf, O., Gockel, S., H¨ansel, F., Hemp, A., Hessenm¨oller, D., Korte, G., Nieschulze, J., Pfeiffer, S., Prati, D., Renner, S., Sch¨oning, I., Schumacher, U., Wells, K., Buscot, F., Kalko, E.K., Linsenmair, K.E., Schulze, E.-D., Weisser, W.W.,

Since I have no link in the Data availability section, but references to links in the reference section, could you identify what those 2 Links are ?"
        ]
    ]
];

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Content-Type: application/json"
]);
$datajson = json_encode($data, JSON_UNESCAPED_SLASHES);
echo $datajson;
curl_setopt($ch, CURLOPT_POSTFIELDS, $datajson);

$response = curl_exec($ch);
$http_status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
print_r( $http_status);

if (curl_errno($ch)) {
    echo "cURL Error: " . curl_error($ch);
} else {
    echo $response;
}

curl_close($ch);
?>
